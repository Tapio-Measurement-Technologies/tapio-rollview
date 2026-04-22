import unittest

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock
from unittest.mock import patch

from gui.widgets.DirectoryView import DirectoryView, selection_flags


class TestDirectoryView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_delete_selects_previous_row_when_available(self):
        self.assertEqual(DirectoryView.get_row_to_select_after_delete(3, 5), 2)

    def test_delete_first_row_selects_first_remaining_row(self):
        self.assertEqual(DirectoryView.get_row_to_select_after_delete(0, 5), 0)

    def test_delete_only_row_has_no_selection_target(self):
        self.assertIsNone(DirectoryView.get_row_to_select_after_delete(0, 1))

    def test_select_first_directory_sets_current_index_to_first_child(self):
        view = DirectoryView()
        try:
            root_index = MagicMock(spec=QModelIndex)
            root_index.isValid.return_value = True
            first_child = MagicMock(spec=QModelIndex)
            first_child.isValid.return_value = True

            selection_model = MagicMock()
            tree_model = MagicMock()
            tree_model.index.return_value = first_child

            view.treeView.rootIndex = MagicMock(return_value=root_index)
            view.treeView.model = MagicMock(return_value=tree_model)
            view.treeView.selectionModel = MagicMock(return_value=selection_model)
            view.treeView.setCurrentIndex = MagicMock()
            view.treeView.setFocus = MagicMock()
            view.treeView.scrollTo = MagicMock()

            view.select_first_directory()

            view.treeView.setFocus.assert_called_once()
            view.treeView.setCurrentIndex.assert_called_once_with(first_child)
            selection_model.setCurrentIndex.assert_called_once_with(first_child, selection_flags)
            view.treeView.scrollTo.assert_called_once_with(first_child)
        finally:
            view.close()

    def test_select_first_directory_skips_when_no_rows(self):
        view = DirectoryView()
        try:
            root_index = MagicMock(spec=QModelIndex)
            root_index.isValid.return_value = True
            first_child = MagicMock(spec=QModelIndex)
            first_child.isValid.return_value = False

            selection_model = MagicMock()
            tree_model = MagicMock()
            tree_model.index.return_value = first_child

            view.treeView.rootIndex = MagicMock(return_value=root_index)
            view.treeView.model = MagicMock(return_value=tree_model)
            view.treeView.selectionModel = MagicMock(return_value=selection_model)
            view.treeView.setCurrentIndex = MagicMock()
            view.treeView.setFocus = MagicMock()
            view.treeView.scrollTo = MagicMock()

            view.select_first_directory()

            view.treeView.setFocus.assert_not_called()
            view.treeView.setCurrentIndex.assert_not_called()
            selection_model.setCurrentIndex.assert_not_called()
            view.treeView.scrollTo.assert_not_called()
        finally:
            view.close()

    def test_restore_focus_reselects_previous_directory_after_model_change(self):
        view = DirectoryView()
        try:
            selected_paths = []
            view._pending_focus_path = "/tmp/selected"
            view.get_selected_directory_path = lambda: "/tmp/other"
            view.select_directory_by_path = selected_paths.append

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view._restore_focus_after_model_change()

            self.assertEqual(selected_paths, ["/tmp/selected"])
            self.assertIsNone(view._pending_focus_path)
        finally:
            view.close()

    def test_restore_focus_skips_reselect_when_focus_already_correct(self):
        view = DirectoryView()
        try:
            selected_paths = []
            view._pending_focus_path = "/tmp/selected"
            view.get_selected_directory_path = lambda: "/tmp/selected"
            view.select_directory_by_path = selected_paths.append

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view._restore_focus_after_model_change()

            self.assertEqual(selected_paths, [])
            self.assertIsNone(view._pending_focus_path)
        finally:
            view.close()

    def test_refresh_inserted_rows_invalidates_date_cache_and_resorts(self):
        view = DirectoryView()
        try:
            parent_index = MagicMock(spec=QModelIndex)
            source_index = MagicMock(spec=QModelIndex)
            source_index.isValid.return_value = True
            proxy_date_index = MagicMock(spec=QModelIndex)
            proxy_date_index.isValid.return_value = True

            proxy_model = MagicMock()
            proxy_model.index.return_value = proxy_date_index
            proxy_model.mapToSource.return_value = source_index
            view.proxy_model = proxy_model
            view.model.filePath = MagicMock(return_value="/tmp/newdir")
            view.model.invalidate_cache = MagicMock()
            view.treeView.header().sortIndicatorSection = MagicMock(return_value=3)
            view.treeView.header().sortIndicatorOrder = MagicMock(return_value=0)

            view.refresh_inserted_rows(parent_index, 2, 2)

            view.model.invalidate_cache.assert_called_once_with("/tmp/newdir")
            proxy_model.dataChanged.emit.assert_called_once_with(
                proxy_date_index,
                proxy_date_index,
                [Qt.ItemDataRole.DisplayRole],
            )
            proxy_model.sort.assert_called_once_with(3, 0)
        finally:
            view.close()

    def test_restore_focus_reapplies_widget_focus_when_tree_had_focus(self):
        view = DirectoryView()
        try:
            view._pending_focus_path = "/tmp/selected"
            view._pending_focus_active = True
            view.get_selected_directory_path = lambda: "/tmp/selected"
            view.select_directory_by_path = MagicMock()
            view.treeView.setFocus = MagicMock()

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view._restore_focus_after_model_change()

            view.select_directory_by_path.assert_not_called()
            view.treeView.setFocus.assert_called_once()
            self.assertFalse(view._pending_focus_active)
        finally:
            view.close()

    def test_restore_selection_after_delete_sets_current_index(self):
        view = DirectoryView()
        try:
            target_index = MagicMock(spec=QModelIndex)
            target_index.isValid.return_value = True
            selection_model = MagicMock()

            view._pending_delete_parent = QPersistentModelIndex()
            view._pending_delete_row = 1
            view.proxy_model.rowCount = MagicMock(return_value=3)
            view.proxy_model.index = MagicMock(return_value=target_index)
            view.treeView.selectionModel = MagicMock(return_value=selection_model)
            view.treeView.setCurrentIndex = MagicMock()
            view.treeView.scrollTo = MagicMock()

            view._restore_selection_after_delete()

            view.treeView.setCurrentIndex.assert_called_once_with(target_index)
            selection_model.setCurrentIndex.assert_called_once_with(target_index, selection_flags)
            view.treeView.scrollTo.assert_called_once_with(target_index)
            self.assertIsNone(view._pending_delete_row)
        finally:
            view.close()

    def test_on_directory_selected_emits_current_directory_path(self):
        view = DirectoryView()
        try:
            current_index = MagicMock(spec=QModelIndex)
            current_index.isValid.return_value = True
            source_index = MagicMock(spec=QModelIndex)
            source_index.isValid.return_value = True

            view.proxy_model.mapToSource = MagicMock(return_value=source_index)
            view.model.filePath = MagicMock(return_value="/tmp/selected")
            emitted_paths = []
            view.directory_selected.connect(emitted_paths.append)

            view.on_directory_selected(current_index, QModelIndex())

            self.assertEqual(emitted_paths, ["/tmp/selected"])
        finally:
            view.close()

    def test_on_directory_selected_ignores_invalid_current_index(self):
        view = DirectoryView()
        try:
            current_index = MagicMock(spec=QModelIndex)
            current_index.isValid.return_value = False
            emitted_paths = []
            view.directory_selected.connect(emitted_paths.append)

            view.on_directory_selected(current_index, QModelIndex())

            self.assertEqual(emitted_paths, [])
        finally:
            view.close()


if __name__ == "__main__":
    unittest.main()
