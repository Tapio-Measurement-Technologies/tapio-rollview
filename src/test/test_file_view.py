import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QModelIndex
from unittest.mock import MagicMock, patch

import store
from gui.widgets.FileView import CustomFilterProxyModel, FileView


class TestFileView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_selected_profile = store.selected_profile

    def tearDown(self):
        store.selected_profile = self.original_selected_profile

    def test_delete_selects_previous_row_when_available(self):
        self.assertEqual(FileView.get_row_to_select_after_delete(3, 5), 2)

    def test_delete_first_row_keeps_focus_at_first_remaining_row(self):
        self.assertEqual(FileView.get_row_to_select_after_delete(0, 5), 0)

    def test_delete_only_row_clears_selection_target(self):
        self.assertIsNone(FileView.get_row_to_select_after_delete(0, 1))

    def test_file_rename_emits_new_selected_file_path_when_selected_profile_renamed(self):
        view = FileView()
        try:
            store.selected_profile = "old.prof"
            emitted_paths = []
            view.file_selected.connect(emitted_paths.append)

            view.on_file_renamed("/tmp/roll", "old.prof", "new.prof")

            self.assertEqual(emitted_paths, ["/tmp/roll/new.prof"])
        finally:
            view.close()

    def test_initial_root_index_is_valid(self):
        view = FileView()
        try:
            self.assertTrue(view.view.rootIndex().isValid())
        finally:
            view.close()

    def test_filter_rejects_non_files(self):
        proxy_model = CustomFilterProxyModel()
        source_model = MagicMock()
        file_info = MagicMock()
        file_info.isFile.return_value = False
        file_info.filePath.return_value = "C:/"
        source_model.index.return_value = MagicMock()
        source_model.fileName.return_value = "C:"
        source_model.fileInfo.return_value = file_info
        proxy_model.sourceModel = MagicMock(return_value=source_model)

        self.assertFalse(proxy_model.filterAcceptsRow(0, QModelIndex()))

    def test_filter_accepts_configured_root_directory_for_proxy_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy_model = CustomFilterProxyModel()
            source_model = MagicMock()
            file_info = MagicMock()
            file_info.isFile.return_value = False
            file_info.filePath.return_value = tmpdir
            source_model.index.return_value = MagicMock()
            source_model.fileName.return_value = os.path.basename(tmpdir)
            source_model.fileInfo.return_value = file_info
            proxy_model.sourceModel = MagicMock(return_value=source_model)

            proxy_model.add_root_path(tmpdir)

            self.assertTrue(proxy_model.filterAcceptsRow(0, QModelIndex()))

    def test_set_directory_logs_instead_of_dialog_when_model_index_not_ready(self):
        view = FileView()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                view._set_root_index_for_path = MagicMock(return_value=False)
                view._note_directory_load_failed = MagicMock()

                with patch("gui.widgets.FileView.show_error_msgbox") as show_error_mock:
                    view.set_directory(tmpdir)

                view._note_directory_load_failed.assert_called_once_with(tmpdir)
                show_error_mock.assert_not_called()
                self.assertEqual(view._pending_directory, tmpdir)
        finally:
            view.close()


if __name__ == "__main__":
    unittest.main()
