"""The device workflow driven through the real GUI, against a fake RQFT.

Scan → the device appears in the list → select it → Sync → profiles land on disk.
Screenshots are captured at each step so the states can be reviewed by eye.
"""

import pytest

from test.fakedevice import FakeRqftDevice

PROFILE_BYTES = bytes(range(256)) * 4


@pytest.fixture
def device():
    with FakeRqftDevice(
        profiles={
            "250520-134139/a.prof": PROFILE_BYTES,
            "250520-134139/b.prof": PROFILE_BYTES[::-1],
        },
        device_name="RQP Fake",
        serial_number="FAKE-0001",
    ) as fake:
        yield fake


@pytest.fixture
def wired_window(main_window, device):
    """main_window with comports pointing at the fake device.

    The main_window fixture only stubs scan_devices while the window is being
    constructed, so the real implementation is in place by the time a test runs.
    """
    with device.patch_comports():
        yield main_window


def test_scan_lists_the_fake_device(wired_window, device, qtbot, snap):
    serial_widget = wired_window.serial_widget
    with qtbot.waitSignal(serial_widget.scan_finished, timeout=15000):
        serial_widget.scan_devices()

    devices = [p for p in serial_widget.view.model.ports if p.device_responded]
    assert len(devices) == 1, f"expected one device, got {serial_widget.view.model.ports}"
    assert devices[0].device == device.port
    assert devices[0].description == "RQP Fake"
    snap(wired_window, "device-found")


def test_sync_pulls_profiles_over_zmodem(wired_window, device, qtbot, tmp_path, snap):
    import store

    store.root_directory = str(tmp_path)
    serial_widget = wired_window.serial_widget

    with qtbot.waitSignal(serial_widget.scan_finished, timeout=15000):
        serial_widget.scan_devices()

    # Select the device the way clicking the row would.
    port_item = next(p for p in serial_widget.view.model.ports if p.device_responded)
    serial_widget.view.model.selected_port = port_item

    with qtbot.waitSignal(
        serial_widget.transferManager.transferFinished, timeout=30000
    ):
        serial_widget.sync_data()

    # transferFinished is emitted from a queued _cleanup on the main thread, which
    # can run before the worker's OS thread has actually exited. Destroying the
    # window at that moment aborts the process with "QThread: Destroyed while
    # thread is still running", so give the thread a moment to die.
    qtbot.wait(300)

    snap(serial_widget.transferDialog, "transfer-dialog")

    assert device.errors == []
    assert sorted(device.files_sent) == [
        "250520-134139/a.prof",
        "250520-134139/b.prof",
    ]
    folder = tmp_path / "250520-134139"
    assert (folder / "a.prof").read_bytes() == PROFILE_BYTES
    assert (folder / "b.prof").read_bytes() == PROFILE_BYTES[::-1]
