"""End-to-end tests of the device path against a fake RQFT on a pseudo-terminal.

These exercise the real pyserial + ZMODEM code, not mocks of it.
"""

import os

import pytest

from test.fakedevice import FakeRqftDevice


@pytest.fixture
def device():
    with FakeRqftDevice(
        profiles={"250520-134139/a.prof": b"\x01\x02\x03\x04" * 64},
        device_name="RQP Fake",
        serial_number="FAKE-0001",
    ) as fake:
        yield fake


def test_scanner_finds_and_identifies_the_device(device, app_modules):
    from workers.port_scanner import PortScannerWorker

    worker = PortScannerWorker()
    with device.patch_comports():
        port_info, responded, error = worker._scan_single_port(device.port_info())

    assert responded, f"device did not respond (error={error})"
    device.wait_for(lambda: device.commands)
    assert port_info.description == "RQP Fake"
    assert port_info.serial_number == "FAKE-0001"
    assert any(c.startswith("RQP+DEVICEINFO?") for c in device.commands)


def test_scan_sets_the_device_clock(device, app_modules):
    from workers.port_scanner import PortScannerWorker

    worker = PortScannerWorker()
    with device.patch_comports():
        worker._scan_single_port(device.port_info())

    assert device.wait_for(lambda: device.timestamps), "device never received RQP+SETTIME"
    assert device.timestamps[0] > 1_600_000_000


def test_silent_port_is_not_reported_as_a_device(app_modules):
    from workers.port_scanner import PortScannerWorker

    with FakeRqftDevice(respond_to_deviceinfo=False) as silent:
        worker = PortScannerWorker()
        _, responded, _ = worker._scan_single_port(silent.port_info())

    assert not responded


def test_zmodem_transfer_writes_the_profile_to_disk(device, tmp_path, app_modules):
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from workers.file_transfer import FileTransferWorker

    worker = FileTransferWorker(device.port, str(tmp_path))
    received = []
    worker.receivingFile.connect(lambda name, left: received.append((name, left)))

    worker.run()
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    assert device.errors == []
    written = tmp_path / "250520-134139" / "a.prof"
    assert written.exists(), f"nothing written; got {list(tmp_path.rglob('*'))}"
    assert written.read_bytes() == b"\x01\x02\x03\x04" * 64
    assert received and received[0][0] == "250520-134139/a.prof"


def test_pty_port_is_a_real_device_node(device):
    assert device.port.startswith("/dev/pts/")
    assert os.path.exists(device.port)
