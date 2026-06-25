import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication

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


if __name__ == "__main__":
    unittest.main()
