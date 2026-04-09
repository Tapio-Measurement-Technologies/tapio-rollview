import unittest

from gui.widgets.FileView import FileView


class TestFileView(unittest.TestCase):
    def test_delete_selects_previous_row_when_available(self):
        self.assertEqual(FileView.get_row_to_select_after_delete(3, 5), 2)

    def test_delete_first_row_keeps_focus_at_first_remaining_row(self):
        self.assertEqual(FileView.get_row_to_select_after_delete(0, 5), 0)

    def test_delete_only_row_clears_selection_target(self):
        self.assertIsNone(FileView.get_row_to_select_after_delete(0, 1))


if __name__ == "__main__":
    unittest.main()
