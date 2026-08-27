import os
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication

from gui.filetransferdialog import FileTransferDialog
from models.FileTransfer import FileTransferItem
from workers.device_connection import ConnectionBridge, SyncError
from workers.file_transfer import FileTransferManager


class TestFileTransferManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_start_transfer_resets_synced_folders(self):
        manager = FileTransferManager()
        manager.synced_folders = ["stale-folder"]

        with patch("workers.file_transfer.QThread") as thread_class, \
             patch("workers.file_transfer.FileTransferWorker") as worker_class:
            thread = MagicMock()
            worker = MagicMock()
            thread_class.return_value = thread
            worker_class.return_value = worker

            manager.start_transfer("COM1", "C:/rolls", MagicMock())

        self.assertEqual(manager.synced_folders, [])


class TestFileTransferDialogProgress(unittest.TestCase):
    def test_total_progress_includes_current_file(self):
        dialog = MagicMock()
        dialog.manager.model.getTotalFileCount.return_value = 4

        dialog.manager.model.getLatestItem.return_value = FileTransferItem(
            "first.prof", 4
        )
        FileTransferDialog.update_progress(dialog)
        dialog.total_progress_bar.setValue.assert_called_with(25)

        dialog.manager.model.getLatestItem.return_value = FileTransferItem(
            "last.prof", 1
        )
        FileTransferDialog.update_progress(dialog)
        dialog.total_progress_bar.setValue.assert_called_with(100)


class TestRqftRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.manager = FileTransferManager()
        self.bridge = ConnectionBridge()
        self.connection = MagicMock()
        self.connection_manager = MagicMock()
        self.connection_manager.get_connection.return_value = self.connection
        self.connection_manager.bridge_for.return_value = self.bridge
        self.manager.set_connection_manager(self.connection_manager)

    def _settle(self):
        """Let queued signals and the zero-delay queue drain run."""
        for _ in range(5):
            QCoreApplication.processEvents()

    def test_rqft_capable_device_routes_to_connection(self):
        with patch("workers.file_transfer.QThread") as thread_class:
            self.manager.start_transfer(
                "COM1", "/rolls", MagicMock(), supports_rqft=True
            )
            thread_class.assert_not_called()

        self.connection_manager.manual_connect.assert_called_once_with("COM1")
        self.connection.request_sync.assert_called_once_with(False)
        self.assertTrue(self.manager.is_transfer_in_progress())
        self.assertTrue(self.manager.has_pending_sync("COM1"))

    def test_rqft_sync_finished_emits_transfer_finished(self):
        finished = []
        self.manager.transferFinished.connect(finished.append)
        on_complete = MagicMock()
        self.manager.start_transfer("COM1", "/rolls", on_complete, supports_rqft=True)

        self.bridge.syncFinished.emit("COM1", ["roll/a.prof"], 0, 0)
        QCoreApplication.processEvents()

        on_complete.assert_called_once()
        self.assertFalse(self.manager.is_transfer_in_progress())
        self.assertEqual(finished, [[os.path.join("/rolls", "roll")]])
        self.assertEqual(self.manager.last_transfer_outcome, "ok")
        self.assertFalse(self.manager.last_transfer_was_auto)

    def test_rqft_sync_failure_reports_partial_folders_without_popup_for_auto(self):
        finished = []
        errors = []
        self.manager.transferFinished.connect(finished.append)
        self.manager.transferError.connect(lambda msg, auto: errors.append(auto))
        self.manager.request_auto_sync("COM1")
        self.connection.request_sync.assert_called_once_with(True)

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            self.bridge.syncFailed.emit(
                "COM1", SyncError("transport", message="gone", fetched=["roll/a.prof"])
            )
            QCoreApplication.processEvents()
            popup.assert_not_called()

        self.assertEqual(errors, [True])
        self.assertFalse(self.manager.is_transfer_in_progress())
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0][0].endswith("roll"))
        self.assertEqual(self.manager.last_transfer_outcome, "error")
        self.assertTrue(self.manager.last_transfer_was_auto)

    def test_cancelled_sync_reports_cancelled_outcome(self):
        self.manager.start_transfer("COM1", "/rolls", None, supports_rqft=True)
        self.assertEqual(self.manager.last_transfer_outcome, "ok")

        with patch("workers.file_transfer.show_error_msgbox") as popup:
            self.bridge.syncFailed.emit("COM1", SyncError("cancelled"))
            QCoreApplication.processEvents()
            popup.assert_not_called()

        self.assertEqual(self.manager.last_transfer_outcome, "cancelled")
        self.assertFalse(self.manager.is_transfer_in_progress())

    def test_legacy_device_sync_never_deletes(self):
        """Pre-RQFT firmware keeps its old behaviour: the ZMODEM path has
        no delete step, so the device decides as before."""
        self.connection_manager.get_connection.return_value = None

        with patch("workers.file_transfer.QThread"), \
             patch("workers.file_transfer.FileTransferWorker"):
            self.manager.start_transfer(
                "COM2", "/rolls", MagicMock(), supports_rqft=False
            )

        self.connection.request_sync.assert_not_called()
        self.assertEqual(self.manager.last_deleted_count, 0)

    def test_rqft_device_falling_back_to_zmodem_does_not_delete(self):
        """A capable device with no live session takes the ZMODEM path,
        which has no delete step."""
        self.connection_manager.get_connection.return_value = None

        with patch("workers.file_transfer.QThread"), \
             patch("workers.file_transfer.FileTransferWorker"):
            self.manager.start_transfer(
                "COM1", "/rolls", MagicMock(), supports_rqft=True
            )

        self.connection.request_sync.assert_not_called()
        self.assertEqual(self.manager.last_deleted_count, 0)

    def test_non_rqft_device_uses_zmodem_thread(self):
        self.connection_manager.get_connection.return_value = None
        with patch("workers.file_transfer.QThread") as thread_class, \
             patch("workers.file_transfer.FileTransferWorker") as worker_class:
            thread_class.return_value = MagicMock()
            worker_class.return_value = MagicMock()
            self.manager.start_transfer(
                "COM2", "/rolls", MagicMock(), supports_rqft=False
            )
            thread_class.assert_called_once()
        self.connection_manager.manual_connect.assert_not_called()

    def test_deleted_count_is_kept_for_the_gui(self):
        self.manager.start_transfer("COM1", "/rolls", None, supports_rqft=True)

        self.bridge.syncFinished.emit("COM1", ["roll/a.prof"], 0, 2)
        QCoreApplication.processEvents()

        self.assertEqual(self.manager.last_deleted_count, 2)

    def test_auto_sync_queue_keeps_one_entry_per_port(self):
        self.manager.start_transfer("COM1", "/rolls", None, supports_rqft=True)

        self.manager.request_auto_sync("COM2")
        self.manager.request_auto_sync("COM2")

        self.assertEqual(self.manager._auto_queue, ["COM2"])
        self.assertTrue(self.manager.has_pending_sync("COM2"))

    def test_notify_for_the_syncing_port_is_queued_not_dropped(self):
        """The running batch was planned before the device rang, so a
        measurement finished mid-sync needs another pass."""
        self.manager.start_transfer("COM1", "/rolls", None, supports_rqft=True)

        self.manager.request_auto_sync("COM1")
        self.assertEqual(self.manager._auto_queue, ["COM1"])

        self.bridge.syncFinished.emit("COM1", [], 0, 0)
        self._settle()

        self.assertEqual(self.manager._auto_queue, [])
        self.connection.request_sync.assert_called_with(True)

    def test_drain_continues_past_a_port_that_lost_its_connection(self):
        self.manager.start_transfer("COM1", "/rolls", None, supports_rqft=True)
        self.manager.request_auto_sync("COM2")
        self.manager.request_auto_sync("COM3")

        reconnected = MagicMock()
        self.connection_manager.get_connection.side_effect = (
            lambda port: None if port == "COM2" else reconnected
        )

        self.bridge.syncFinished.emit("COM1", [], 0, 0)
        self._settle()

        self.assertEqual(self.manager._auto_queue, [])
        reconnected.request_sync.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
