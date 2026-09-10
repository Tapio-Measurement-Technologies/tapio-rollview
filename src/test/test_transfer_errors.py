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
    ConnectionState,
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

    def test_the_port_is_opened_with_a_deadline_on_its_writes(self):
        """Without one, pyserial waits on a write forever, and a port whose
        device has been switched off never completes one: that is what left
        a sync running with a bar that never moved."""
        opened = {}

        def record(**kwargs):
            opened.update(kwargs)
            return FakeSerial([])

        self.run_worker(record)

        self.assertGreater(opened.get("write_timeout", 0), 0)

    def test_a_write_that_times_out_is_a_lost_link(self):
        class StalledSerial(FakeSerial):
            def write(self, data):
                raise serial.SerialTimeoutException("Write timeout")

        worker, errors = self.run_worker(lambda **kwargs: StalledSerial([b"x"]))

        self.assertEqual(worker.error_cause, CAUSE_LINK_LOST)
        self.assertEqual(len(errors), 1)

    def test_stopping_does_not_close_the_port_from_the_callers_thread(self):
        """Cancel runs on the thread that draws the window. Closing the
        port there hands the driver a handle it still has I/O in flight
        on, and a Cancel that blocks is a window that stops redrawing."""
        port = FakeSerial([])
        worker = ZmodemTransferWorker("COM6", "C:/rolls")
        worker.serial = port
        worker._running = True

        worker.stop()

        self.assertTrue(port.is_open)
        self.assertFalse(worker._running)
        # The worker closes it, on its way out.
        worker._close_port()
        self.assertFalse(port.is_open)

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

    def test_the_box_carries_the_fault_and_the_remedy(self):
        """The box is where a failed sync answers: it has room for both,
        and the status row has room for neither."""
        manager = FileTransferManager()
        manager._active_port = "COM6"
        manager._active_unit_name = "Tapio RQP Live (1428495563)"
        manager.worker = SimpleNamespace(error_cause=CAUSE_HELD)

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            manager.on_transfer_error(WIN_HELD)

        body, title = popup.call_args.args
        self.assertEqual(title, "Port in use")
        self.assertIn("COM6 is in use by another program.", body)
        self.assertIn("Close the other program", body)
        self.assertNotIn("PermissionError", body)
        self.assertEqual(manager.last_transfer_outcome, "error")

    def test_the_unit_name_comes_from_the_sync_request(self):
        manager = FileTransferManager()
        manager.set_connection_manager(MagicMock(device_label=MagicMock(return_value="COM6")))
        with patch("workers.file_transfer.QThread"), patch("workers.file_transfer.FileTransferWorker"):
            manager.start_transfer("COM6", "C:/rolls", None, unit_name="Tapio RQP Live (1)")
        self.assertEqual(manager._active_unit_name, "Tapio RQP Live (1)")


class TestBusyDevice(unittest.TestCase):
    """A sync pressed while the device is measuring is not a fault. It
    waits, quietly, and runs when the device comes back."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_manager(self):
        manager = FileTransferManager()
        manager._connection_manager = MagicMock()
        manager._active_port = "COM6"
        manager._active_is_auto = False
        manager._transfer_in_progress = True
        manager.sync_folder_path = "C:/rolls"
        manager._on_complete_callback = None
        manager._active_bridge = None
        return manager

    def test_a_manual_sync_the_device_refuses_shows_no_box(self):
        manager = self.make_manager()

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            manager._on_rqft_failed("COM6", SyncError("busy", message="E_BUSY"))

        popup.assert_not_called()
        self.assertEqual(manager.last_transfer_outcome, "busy")
        self.assertEqual(manager._retry_after_busy, ("COM6", "C:/rolls", None))

    def test_the_refused_sync_runs_again_when_the_device_is_back(self):
        manager = self.make_manager()
        with patch("workers.file_transfer.show_error_msgbox"):
            manager._on_rqft_failed("COM6", SyncError("busy", message="E_BUSY"))

        with patch.object(manager, "start_transfer") as start:
            manager._on_connection_state_changed("COM6", ConnectionState.CONNECTED)
            QApplication.processEvents()

        start.assert_called_once_with("COM6", "C:/rolls", None, supports_rqft=True)
        self.assertIsNone(manager._retry_after_busy)

    def test_the_devices_own_doorbell_runs_the_operators_sync_instead(self):
        manager = self.make_manager()
        with patch("workers.file_transfer.show_error_msgbox"):
            manager._on_rqft_failed("COM6", SyncError("busy", message="E_BUSY"))
        manager._transfer_in_progress = False

        with patch.object(manager, "start_transfer") as start, \
             patch.object(manager, "_start_auto_sync") as auto:
            manager.request_auto_sync("COM6")

        start.assert_called_once()
        auto.assert_not_called()

    def test_an_automatic_sync_the_device_refuses_stays_quiet_and_does_not_retry(self):
        manager = self.make_manager()
        manager._active_is_auto = True

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            manager._on_rqft_failed("COM6", SyncError("busy", message="E_BUSY"))

        popup.assert_not_called()
        self.assertIsNone(manager._retry_after_busy)


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
