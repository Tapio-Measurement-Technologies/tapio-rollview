import unittest
from unittest.mock import MagicMock, patch

import settings
from serial.tools import list_ports_common
from utils import preferences
from workers.port_scanner import PortScanner, PortScannerWorker


def make_port(
    device,
    description="",
    vid=None,
    pid=None,
    serial_number=None,
    hwid="",
    manufacturer=None,
    product=None,
):
    port = list_ports_common.ListPortInfo(device)
    port.description = description
    port.name = device
    port.product = product
    port.manufacturer = manufacturer
    port.hwid = hwid
    port.vid = vid
    port.pid = pid
    port.serial_number = serial_number
    return port


class FakeSerial:
    def __init__(self, response=b""):
        self.response = response
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def readline(self):
        return self.response

    def close(self):
        self.is_open = False


class TestPortScannerWorker(unittest.TestCase):
    def setUp(self):
        self.original_allowed_usb_ids = settings.ALLOWED_SERIAL_USB_IDS
        self.original_bluetooth_port_markers = settings.SERIAL_BLUETOOTH_PORT_MARKERS
        self.original_pinned_serial_ports = preferences.pinned_serial_ports
        settings.ALLOWED_SERIAL_USB_IDS = {(0x16C0, 0x0483)}
        settings.SERIAL_BLUETOOTH_PORT_MARKERS = (
            "bluetooth",
            "bthenum",
            "bthmodem",
            "rfcomm",
        )
        preferences.pinned_serial_ports = set()

    def tearDown(self):
        settings.ALLOWED_SERIAL_USB_IDS = self.original_allowed_usb_ids
        settings.SERIAL_BLUETOOTH_PORT_MARKERS = self.original_bluetooth_port_markers
        preferences.pinned_serial_ports = self.original_pinned_serial_ports

    def test_usb_vid_pid_candidate_is_probed(self):
        worker = PortScannerWorker()
        port = make_port("COM1", vid=0x16C0, pid=0x0483)

        self.assertTrue(worker._should_probe_port(port))

    def test_nonmatching_usb_port_is_not_probed(self):
        worker = PortScannerWorker()
        port = make_port("COM2", vid=0x1234, pid=0x5678)

        self.assertFalse(worker._should_probe_port(port))

    def test_bluetooth_description_candidate_is_probed(self):
        worker = PortScannerWorker()
        port = make_port("COM3", description="Standard Serial over Bluetooth link")

        self.assertTrue(worker._should_probe_port(port))

    def test_bluetooth_hwid_candidate_is_probed(self):
        worker = PortScannerWorker()
        port = make_port(
            "COM5",
            description="Standard Serial Port",
            hwid="BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}",
        )

        self.assertTrue(worker._should_probe_port(port))

    def test_pinned_port_is_probed_without_allowed_metadata(self):
        preferences.pinned_serial_ports = {"COM4"}
        worker = PortScannerWorker()
        port = make_port("COM4", description="Standard Serial Port")

        self.assertTrue(worker._should_probe_port(port))

    @patch("workers.port_scanner.send_timestamp")
    @patch("workers.port_scanner.serial.Serial")
    @patch("workers.port_scanner.serial.tools.list_ports.comports")
    def test_run_returns_all_ports_but_only_opens_candidates(
        self,
        mock_comports,
        mock_serial,
        _mock_send_timestamp,
    ):
        ports = [
            make_port("COM1", vid=0x16C0, pid=0x0483),
            make_port("COM2", vid=0x1234, pid=0x5678),
            make_port("COM3", description="Standard Serial over Bluetooth link"),
        ]
        mock_comports.return_value = ports

        def open_fake_serial(port, **_kwargs):
            if port in {"COM1", "COM3"}:
                return FakeSerial(
                    b'{"deviceName": "Tapio RQP Live", "serialNumber": "ABC123"}\n'
                )
            return FakeSerial(b"")

        mock_serial.side_effect = open_fake_serial
        finished = []
        worker = PortScannerWorker(max_workers=1)
        worker.finished.connect(finished.append)

        worker.run()

        self.assertEqual({port.device for port in finished[0]}, {"COM1", "COM2", "COM3"})
        opened_ports = [call.kwargs["port"] for call in mock_serial.call_args_list]
        self.assertEqual(opened_ports, ["COM1", "COM3"])
        responded = {port.device: port.device_responded for port in finished[0]}
        self.assertTrue(responded["COM1"])
        self.assertFalse(responded["COM2"])
        self.assertTrue(responded["COM3"])

    @patch("workers.port_scanner.send_timestamp")
    @patch("workers.port_scanner.serial.Serial")
    @patch("workers.port_scanner.serial.tools.list_ports.comports")
    def test_run_probes_bluetooth_serial_ports_without_name_filter(
        self,
        mock_comports,
        mock_serial,
        _mock_send_timestamp,
    ):
        mock_comports.return_value = [
            make_port(
                "COM5",
                description="Standard Serial over Bluetooth link",
                hwid="BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}",
            )
        ]
        mock_serial.return_value = FakeSerial(
            b'{"deviceName": "Tapio RQP Live", "serialNumber": "BT123"}\n'
        )
        finished = []
        worker = PortScannerWorker(max_workers=1)
        worker.finished.connect(finished.append)

        worker.run()

        opened_ports = [call.kwargs["port"] for call in mock_serial.call_args_list]
        self.assertEqual(opened_ports, ["COM5"])
        self.assertEqual(finished[0][0].device, "COM5")
        self.assertTrue(finished[0][0].device_responded)

    @patch("workers.port_scanner.serial.tools.list_ports.comports")
    def test_missing_pinned_ports_are_returned_and_probed(self, mock_comports):
        preferences.pinned_serial_ports = {"COM10"}
        mock_comports.return_value = []
        finished = []
        worker = PortScannerWorker(max_workers=1)
        worker._scan_single_port = MagicMock(return_value=(
            make_port("COM10"),
            False,
            None,
        ))
        worker.finished.connect(finished.append)

        worker.run()

        worker._scan_single_port.assert_called_once()
        self.assertEqual([port.device for port in finished[0]], ["COM10"])

    @patch("workers.port_scanner.send_timestamp")
    @patch("workers.port_scanner.serial.Serial")
    def test_invalid_response_does_not_mark_device_responded(self, mock_serial, mock_send_timestamp):
        mock_serial.return_value = FakeSerial(b'{"deviceName": "Tapio RQP Live"}\n')
        worker = PortScannerWorker(max_workers=1)
        port = make_port("COM1", vid=0x16C0, pid=0x0483)

        _port_info, device_responded, _error = worker._scan_single_port(port)

        self.assertFalse(device_responded)
        mock_send_timestamp.assert_not_called()


class TestPortScanner(unittest.TestCase):
    def test_is_running_handles_deleted_qthread_wrapper(self):
        scanner = PortScanner()
        scanner._thread = MagicMock()
        scanner._worker = MagicMock()
        scanner._thread.isRunning.side_effect = RuntimeError(
            "Internal C++ object (PySide6.QtCore.QThread) already deleted."
        )

        self.assertFalse(scanner.is_running())
        self.assertIsNone(scanner._thread)
        self.assertIsNone(scanner._worker)


if __name__ == "__main__":
    unittest.main()
