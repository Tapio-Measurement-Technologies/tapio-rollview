import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QFileSystemModel
from PySide6.QtWidgets import QApplication, QDialog

from gui.widgets.ContextMenuTreeView import ContextMenuTreeView


class TestContextMenuTreeView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rename_uses_model_set_data_to_keep_selection_on_item(self):
        model = QStandardItemModel()
        view = ContextMenuTreeView(model)
        try:
            index = MagicMock(spec=QModelIndex)
            name_index = MagicMock(spec=QModelIndex)
            index.siblingAtColumn.return_value = name_index
            name_index.parent.return_value = QModelIndex()
            view._model.fileName = MagicMock(return_value="old.prof")
            view._model.setData = MagicMock(return_value=True)

            dialog = MagicMock()
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.text_value.return_value = "new.prof"

            with patch("gui.widgets.ContextMenuTreeView.RenameDialog", return_value=dialog):
                view.rename_file(index)

            index.siblingAtColumn.assert_called_once_with(0)
            view._model.setData.assert_called_once_with(name_index, "new.prof", Qt.ItemDataRole.EditRole)
        finally:
            view.close()

    def test_filesystem_model_is_writable_for_rename(self):
        model = QFileSystemModel()
        view = ContextMenuTreeView(model)
        try:
            self.assertFalse(model.isReadOnly())
        finally:
            view.close()


if __name__ == "__main__":
    unittest.main()
