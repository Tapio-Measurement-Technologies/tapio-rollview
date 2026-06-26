import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStringListModel
from PySide6.QtWidgets import QApplication, QListView

from gui.widgets.DirectoryView import DirectoryView
from gui.widgets.EmptyStateView import view_is_empty
from gui.widgets.FileView import FileView
from gui.widgets.serialports import SerialPortView


class TestEmptyStateView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_helper_detects_empty_root_rows(self):
        view = QListView()
        model = QStringListModel([])
        view.setModel(model)
        try:
            self.assertTrue(view_is_empty(view))

            model.setStringList(["item"])

            self.assertFalse(view_is_empty(view))
        finally:
            view.close()

    def test_target_views_have_empty_messages(self):
        serial_view = SerialPortView()
        directory_view = DirectoryView()
        file_view = FileView()
        try:
            self.assertEqual(serial_view.empty_message(), "No devices found")
            self.assertEqual(directory_view.treeView.empty_message(), "No folders in selected directory")
            self.assertEqual(file_view.view.empty_message(), "No profiles in selected folder")
        finally:
            serial_view.close()
            directory_view.close()
            file_view.close()

    def test_helper_handles_views_with_model_attribute(self):
        view = SerialPortView()
        try:
            self.assertTrue(view_is_empty(view))
        finally:
            view.close()


if __name__ == "__main__":
    unittest.main()
