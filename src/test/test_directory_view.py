import unittest

from gui.widgets.DirectoryView import DirectoryView


class TestDirectoryView(unittest.TestCase):
    def test_delete_selects_previous_row_when_available(self):
        self.assertEqual(DirectoryView.get_row_to_select_after_delete(3, 5), 2)

    def test_delete_first_row_selects_first_remaining_row(self):
        self.assertEqual(DirectoryView.get_row_to_select_after_delete(0, 5), 0)

    def test_delete_only_row_has_no_selection_target(self):
        self.assertIsNone(DirectoryView.get_row_to_select_after_delete(0, 1))


if __name__ == "__main__":
    unittest.main()
