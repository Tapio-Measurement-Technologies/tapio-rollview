"""Handing a folder to the desktop's file manager.

The Windows branch is the one with a trap in it: explorer.exe wants the path
attached to its switch, and an argument list quietly puts a space in between.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.file_utils import open_in_file_explorer

FOLDER = r"C:\Users\Someone\.tapiorqp"
SELECTED = r"C:\Users\Someone\.tapiorqp\roll 12"


class TestOpenInFileExplorer(unittest.TestCase):
    def test_windows_selects_the_folder_in_one_argument(self):
        """With a space after the comma Explorer drops the selection.

        It then opens the default folder instead, which is what "Open in file
        explorer" did for the selected roll.
        """
        with patch("utils.file_utils.platform.system", return_value="Windows"), \
             patch("utils.file_utils.os.path.exists", return_value=True), \
             patch("utils.file_utils.subprocess.run") as run:
            open_in_file_explorer(FOLDER, SELECTED)

        run.assert_called_once_with(f'explorer /select,"{SELECTED}"')

    def test_windows_without_a_selection_opens_the_folder(self):
        with patch("utils.file_utils.platform.system", return_value="Windows"), \
             patch("utils.file_utils.os.path.exists", return_value=True), \
             patch("utils.file_utils.os.startfile", create=True) as startfile, \
             patch("utils.file_utils.subprocess.run") as run:
            open_in_file_explorer(FOLDER)

        startfile.assert_called_once_with(FOLDER)
        run.assert_not_called()

    def test_a_missing_folder_says_so_instead_of_opening_anything(self):
        with patch("utils.file_utils.platform.system", return_value="Windows"), \
             patch("utils.file_utils.os.path.exists", return_value=False), \
             patch("utils.file_utils.show_error_msgbox") as error_box, \
             patch("utils.file_utils.subprocess.run") as run:
            open_in_file_explorer(FOLDER, SELECTED)

        error_box.assert_called_once()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
