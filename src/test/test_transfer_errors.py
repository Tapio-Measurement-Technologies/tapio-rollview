"""How a failed transfer reaches the operator, worded by cause.

The ZMODEM worker sorts an open failure, a port that fails mid-transfer
and a device that never answers into causes; the manager turns a cause
into a message box with the cause as its title and the same sentence in
the status bar. The RQFT path words its transport failures the same way.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import serial
from PySide6.QtWidgets import QApplication

from utils.serial_errors import CAUSE_GONE, CAUSE_HELD, CAUSE_LINK_LOST, CAUSE_SILENT
from workers.device_connection import (
    DeviceConnectionManager,
    SyncError,
    describe_sync_error,
    sync_error_title,
)
from workers.file_transfer import FileTransferManager, ZmodemTransferWorker

WIN_HELD = "could not open port 'COM6': PermissionError(13, 'Access is denied.', None, 5)"
WIN_READ_FAILED = "ClearCommError failed (PermissionError(13, 'The device does not recognize the command.', None, 22))"


class FakeSerial:
    """A port whose reads come from a script: bytes, b"" for a quiet
    read, or an exception to raise."""

    def __init__(self, reads):
        self.reads = list(reads)
        self.is_open = True

    def read_all(self):
        return b""

    def read(self, size):
        if not self.reads:
            return b""
        item = self.reads.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def write(self, data):
        return len(data)

    def close(self):
        self.is_open = False


class FakeReceiver:
    """Stands in for the ZMODEM receiver: reads until the worker stops it."""

    def __init__(self, getc, putc, sender):
        self.getc = getc

    def recv(self, basedir):
        while True:
            self.getc(1)


class TestZmodemWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_worker(self, port_factory):
        worker = ZmodemTransferWorker("COM6", "C:/rolls")
        errors = []
        finished = []
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))
        with patch("workers.file_transfer.serial.Serial", side_effect=port_factory), \
             patch("workers.file_transfer.ZMODEM", FakeReceiver), \
             patch("workers.file_transfer.time.sleep"), \
             patch("workers.file_transfer.DEVICE_SILENCE_TIMEOUT_S", 0.0):
            worker.run()
        self.assertEqual(finished, [True])
        return worker, errors

    def test_a_port_that_will_not_open_reports_why(self):
        def refuse(**kwargs):
            raise serial.SerialException(WIN_HELD)

        worker, errors = self.run_worker(refuse)

        self.assertEqual(worker.error_cause, CAUSE_HELD)
        self.assertEqual(errors, [WIN_HELD])

    def test_a_port_that_fails_mid_transfer_is_a_lost_link(self):
        port = FakeSerial([b"**\x18B", serial.SerialException(WIN_READ_FAILED)])

        worker, errors = self.run_worker(lambda **kwargs: port)

        self.assertEqual(worker.error_cause, CAUSE_LINK_LOST)
        self.assertEqual(errors, [WIN_READ_FAILED])
        self.assertFalse(port.is_open)

    def test_a_device_that_never_answers_is_reported_not_called_up_to_date(self):
        port = FakeSerial([])

        worker, errors = self.run_worker(lambda **kwargs: port)

        self.assertEqual(worker.error_cause, CAUSE_SILENT)
        self.assertEqual(len(errors), 1)

    def test_a_device_that_goes_quiet_after_answering_ends_the_transfer(self):
        """The receiver re-sends its header for as long as the device says
        nothing it understands, so a unit switched off part way through
        used to leave a bar that would never move. One byte of console
        noise must not disable the watchdog for the rest of the sync."""
        port = FakeSerial([b"RQP+OK\r\n"])

        worker, errors = self.run_worker(lambda **kwargs: port)

        self.assertEqual(worker.error_cause, CAUSE_LINK_LOST)
        self.assertEqual(len(errors), 1)

    def test_bytes_keep_a_transfer_in_flight_alive(self):
        """The watchdog counts from the last byte, so a sync that is
        moving is never cut short."""
        port = FakeSerial([b"a", b"", b"b", b"", b"c"])
        worker = ZmodemTransferWorker("COM6", "C:/rolls")
        with patch("workers.file_transfer.serial.Serial", return_value=port), \
             patch("workers.file_transfer.ZMODEM", FakeReceiver), \
             patch("workers.file_transfer.time.sleep"), \
             patch("workers.file_transfer.DEVICE_SILENCE_TIMEOUT_S", 30.0):
            worker.stop_after = None
            import threading
            done = threading.Event()
            thread = threading.Thread(target=lambda: (worker.run(), done.set()), daemon=True)
            thread.start()
            self.assertFalse(done.wait(0.5), "a moving transfer was cut short")
            worker.stop()
            self.assertTrue(done.wait(3.0))

        self.assertIsNone(worker.error_cause)

    def test_a_stop_from_the_operator_is_not_an_error(self):
        worker_ref = {}

        class StoppingSerial(FakeSerial):
            def read(self, size):
                # What cancel does: stop() closes the port under the read.
                worker_ref["w"].stop()
                raise serial.SerialException("port closed")

        port = StoppingSerial([])
        worker = ZmodemTransferWorker("COM6", "C:/rolls")
        worker_ref["w"] = worker
        errors = []
        worker.error.connect(errors.append)
        with patch("workers.file_transfer.serial.Serial", return_value=port), \
             patch("workers.file_transfer.ZMODEM", FakeReceiver), \
             patch("workers.file_transfer.time.sleep"):
            worker.run()

        self.assertEqual(errors, [])
        self.assertIsNone(worker.error_cause)


class TestManagerWording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_box_carries_the_cause_and_the_status_bar_the_sentence(self):
        manager = FileTransferManager()
        manager._active_port = "COM6"
        manager._active_unit_name = "Tapio RQP Live (1428495563)"
        manager.worker = SimpleNamespace(error_cause=CAUSE_HELD)
        statuses = []
        manager.transferError.connect(lambda message, auto: statuses.append((message, auto)))

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            manager.on_transfer_error(WIN_HELD)

        body, title = popup.call_args.args
        self.assertEqual(title, "Port in use")
        self.assertIn("COM6 is in use by another program.", body)
        self.assertNotIn("PermissionError", body)
        self.assertEqual(statuses, [(body, False)])
        self.assertEqual(manager.last_transfer_outcome, "error")

    def test_the_unit_name_comes_from_the_sync_request(self):
        manager = FileTransferManager()
        manager.set_connection_manager(MagicMock(device_label=MagicMock(return_value="COM6")))
        with patch("workers.file_transfer.QThread"), patch("workers.file_transfer.FileTransferWorker"):
            manager.start_transfer("COM6", "C:/rolls", None, unit_name="Tapio RQP Live (1)")
        self.assertEqual(manager._active_unit_name, "Tapio RQP Live (1)")


class TestRqftWording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_transport_failure_is_worded_by_cause(self):
        error = SyncError("transport", message=WIN_HELD)
        self.assertIn("COM6 is in use by another program.", describe_sync_error(error, "COM6", "RQP (1)"))
        self.assertEqual(sync_error_title(error), "Port in use")

    def test_a_failure_after_the_open_is_a_lost_link(self):
        error = SyncError("transport", message=WIN_READ_FAILED, opened=True)
        self.assertIn("dropped", describe_sync_error(error, "COM6", "RQP (1)"))
        self.assertEqual(sync_error_title(error), "Connection lost")

    def test_other_failures_keep_their_wording_under_a_sync_failed_title(self):
        error = SyncError("timeout", message="no progress")
        self.assertEqual(sync_error_title(error), "Sync failed")
        self.assertNotIn("no progress", describe_sync_error(error))

    def test_a_lost_connection_is_described_from_the_workers_cause(self):
        manager = DeviceConnectionManager()
        manager._workers["COM4"] = SimpleNamespace(last_error_cause=CAUSE_GONE)

        text = manager.describe_lost_connection("COM4")

        self.assertIn("COM4 is no longer there.", text)
        self.assertIn("Reconnect the device", text)


if __name__ == "__main__":
    unittest.main()
