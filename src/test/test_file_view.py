import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import store
from gui.widgets.FileView import FileView


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


if __name__ == "__main__":
    unittest.main()
