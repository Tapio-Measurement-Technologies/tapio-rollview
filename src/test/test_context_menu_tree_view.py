import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QFileSystemModel
from PySide6.QtWidgets import QApplication, QDialog

from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
from utils.translation import _
from test.qtcleanup import destroy


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
            destroy(view)

    def test_the_postprocess_item_is_off_unless_a_view_asks_for_it(self):
        """The file list's rows are profiles, not roll folders."""
        from PySide6.QtWidgets import QMenu

        model = QStandardItemModel()
        model.appendRow(QStandardItem("a-roll"))
        view = ContextMenuTreeView(model)
        try:
            index = model.index(0, 0)
            view.setCurrentIndex(index)
            with patch.object(QMenu, "exec_"):
                view.open_context_menu(view.visualRect(index).center())

            texts = [action.text() for action in view.findChildren(QAction)]
            self.assertNotIn(_("CONTEXT_MENU_RUN_POSTPROCESSORS"), texts)
        finally:
            destroy(view)

    def test_a_view_that_opts_in_offers_the_row_to_the_postprocessors(self):
        from PySide6.QtWidgets import QMenu

        model = QStandardItemModel()
        model.appendRow(QStandardItem("a-roll"))
        view = ContextMenuTreeView(model)
        view.postprocess_action_enabled = True
        try:
            index = model.index(0, 0)
            view.setCurrentIndex(index)
            requested = []
            view.postprocessRequested.connect(requested.append)

            with patch.object(QMenu, "exec_"):
                view.open_context_menu(view.visualRect(index).center())

            action = next(
                action for action in view.findChildren(QAction)
                if action.text() == _("CONTEXT_MENU_RUN_POSTPROCESSORS")
            )
            action.trigger()
            self.assertEqual([i.row() for i in requested], [0])
        finally:
            destroy(view)

    def test_filesystem_model_is_writable_for_rename(self):
        model = QFileSystemModel()
        view = ContextMenuTreeView(model)
        try:
            self.assertFalse(model.isReadOnly())
        finally:
            destroy(view)


if __name__ == "__main__":
    unittest.main()
