import os
import re
import tempfile
import unittest

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock
from unittest.mock import patch

from gui.widgets.DirectoryView import (
    CustomFileSystemModel,
    DirectorySortFilterProxyModel,
    DirectoryView,
    selection_flags,
)
from gui.widgets.RegexFilterLineEdit import RegexFilterLineEdit
from utils.translation import _


class FakeDirectoryModel(QAbstractListModel):
    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def rowCount(self, parent=QModelIndex()):
        return len(self.paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.paths[index.row()]
        return None

    def filePath(self, index):
        return self.paths[index.row()]


class TestDirectoryView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate, timeout_ms=1000):
        from PySide6.QtTest import QTest

        for _ in range(max(1, timeout_ms // 50)):
            QApplication.processEvents()
            if predicate():
                return True
            QTest.qWait(50)
        QApplication.processEvents()
        return predicate()

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

    def test_select_first_directory_can_leave_current_focus_unchanged(self):
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

            view.select_first_directory(set_focus=False)

            view.treeView.setFocus.assert_not_called()
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
            view.select_directory_by_path = lambda path, warn=True: selected_paths.append(path) or True

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
            view.select_directory_by_path = lambda path, warn=True: selected_paths.append(path) or True

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view._restore_focus_after_model_change()

            self.assertEqual(selected_paths, [])
            self.assertIsNone(view._pending_focus_path)
        finally:
            view.close()

    def test_restore_focus_selects_first_directory_without_stealing_input_focus(self):
        view = DirectoryView()
        try:
            view._pending_focus_path = "/tmp/selected"
            view._pending_focus_active = False
            view.get_selected_directory_path = lambda: "/tmp/other"
            view.select_directory_by_path = MagicMock(return_value=False)
            view.select_first_directory = MagicMock()
            view.treeView.setFocus = MagicMock()

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view._restore_focus_after_model_change()

            view.select_directory_by_path.assert_called_once_with("/tmp/selected", warn=False)
            view.select_first_directory.assert_called_once_with(set_focus=False)
            view.treeView.setFocus.assert_not_called()
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

    def test_on_directory_renamed_emits_new_selected_path(self):
        view = DirectoryView()
        try:
            view._root_directory = "/tmp/root"
            view.get_selected_directory_path = MagicMock(return_value="/tmp/root/new")
            view.watch_directory_and_subdirs = MagicMock()
            view.model.invalidate_cache = MagicMock()
            emitted_paths = []
            view.directory_selected.connect(emitted_paths.append)

            with patch("gui.widgets.DirectoryView.os.path.isdir", return_value=True):
                view.on_directory_renamed("/tmp/root", "old", "new")

            view.model.invalidate_cache.assert_any_call("/tmp/root/old")
            view.model.invalidate_cache.assert_any_call("/tmp/root/new")
            view.watch_directory_and_subdirs.assert_called_once_with("/tmp/root")
            self.assertEqual(emitted_paths, ["/tmp/root/new"])
        finally:
            view.close()

    def test_change_root_directory_logs_instead_of_dialog_when_model_index_not_ready(self):
        view = DirectoryView()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                view.watch_directory_and_subdirs = MagicMock()
                view.select_first_directory = MagicMock()
                view._note_directory_load_failed = MagicMock()
                emitted_directories = []
                view.root_directory_changed.connect(emitted_directories.append)

                with patch.object(view.proxy_model, "mapFromSource", return_value=QModelIndex()), \
                     patch("gui.widgets.DirectoryView.show_error_msgbox") as show_error_mock:
                    view.change_root_directory(tmpdir)

                view._note_directory_load_failed.assert_called_once_with(tmpdir)
                show_error_mock.assert_not_called()
                self.assertEqual(view._root_directory, tmpdir)
                self.assertEqual(emitted_directories, [tmpdir])
                view.watch_directory_and_subdirs.assert_called_once_with(tmpdir)
                view.select_first_directory.assert_not_called()
        finally:
            view.close()

    def test_root_change_discards_stale_selection_before_async_initial_selection(self):
        view = DirectoryView()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                old_root = os.path.join(tmpdir, "old-root")
                old_roll = os.path.join(old_root, "old-roll")
                empty_root = os.path.join(tmpdir, "empty-root")
                new_root = os.path.join(tmpdir, "new-root")
                new_roll = os.path.join(new_root, "new-roll")
                for directory in (old_roll, empty_root, new_roll):
                    os.makedirs(directory)

                emitted_paths = []
                view.directory_selected.connect(emitted_paths.append)

                view.change_root_directory(old_root)
                self.assertTrue(self.wait_until(lambda: view.get_selected_directory_path() == old_roll))

                emitted_paths.clear()
                view.change_root_directory(empty_root)
                self.assertTrue(self.wait_until(lambda: view.proxy_model.rowCount(view.treeView.rootIndex()) == 0))
                self.assertIsNone(view.get_selected_directory_path())
                self.assertEqual(emitted_paths, [])

                view.change_root_directory(new_root)
                self.assertTrue(self.wait_until(lambda: view.get_selected_directory_path() == new_roll))
                self.assertEqual(emitted_paths, [new_roll])
        finally:
            view.close()

    def test_directory_date_refresh_paths_include_synced_folder_ancestors(self):
        view = DirectoryView()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                roll_dir = os.path.join(tmpdir, "roll-1")
                nested_dir = os.path.join(roll_dir, "nested")
                os.makedirs(nested_dir)
                view._root_directory = tmpdir

                refresh_paths = view._directory_date_refresh_paths([nested_dir])

                self.assertEqual(
                    [DirectoryView._normalized_path_key(path) for path in refresh_paths],
                    [
                        DirectoryView._normalized_path_key(nested_dir),
                        DirectoryView._normalized_path_key(roll_dir),
                        DirectoryView._normalized_path_key(tmpdir),
                    ],
                )
        finally:
            view.close()

    def test_refresh_directory_dates_invalidates_emits_sorts_and_rewatches(self):
        view = DirectoryView()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                roll_dir = os.path.join(tmpdir, "roll-1")
                os.mkdir(roll_dir)
                view._root_directory = tmpdir
                view.preserve_current_directory_focus = MagicMock()
                view.watch_directory_and_subdirs = MagicMock()
                view.model.invalidate_cache = MagicMock()
                view._emit_directory_date_changed = MagicMock()
                view.proxy_model.sort = MagicMock()
                view.schedule_focus_restore = MagicMock()
                view.treeView.header().sortIndicatorSection = MagicMock(return_value=3)
                view.treeView.header().sortIndicatorOrder = MagicMock(return_value=Qt.SortOrder.DescendingOrder)

                view.refresh_directory_dates([roll_dir])

                view.preserve_current_directory_focus.assert_called_once()
                view.model.invalidate_cache.assert_any_call(roll_dir)
                view.model.invalidate_cache.assert_any_call(tmpdir)
                view._emit_directory_date_changed.assert_any_call(roll_dir)
                view.watch_directory_and_subdirs.assert_called_once_with(tmpdir)
                view.proxy_model.sort.assert_called_once_with(3, Qt.SortOrder.DescendingOrder)
                view.schedule_focus_restore.assert_called_once()
        finally:
            view.close()

    def test_latest_modified_date_uses_only_real_profile_files(self):
        model = CustomFileSystemModel()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                roll_dir = os.path.join(tmpdir, "roll-1")
                os.mkdir(roll_dir)
                profile_path = os.path.join(roll_dir, "a.prof")
                mean_path = os.path.join(roll_dir, "mean.prof")
                unrelated_path = os.path.join(roll_dir, "newer.prof.txt")

                for path in (profile_path, mean_path, unrelated_path):
                    with open(path, "wb") as handle:
                        handle.write(b"data")

                profile_mtime = 1_700_000_000
                os.utime(profile_path, (profile_mtime, profile_mtime))
                os.utime(mean_path, (profile_mtime + 100, profile_mtime + 100))
                os.utime(unrelated_path, (profile_mtime + 200, profile_mtime + 200))

                latest_date = model.get_latest_modified_date(roll_dir)

                self.assertIsNotNone(latest_date)
                self.assertAlmostEqual(latest_date.timestamp(), profile_mtime, delta=1)
        finally:
            model.deleteLater()

    def test_directory_proxy_filters_folder_names_by_regex(self):
        proxy = DirectorySortFilterProxyModel()
        proxy.excluded_folders = []
        model = FakeDirectoryModel([
            "/tmp/Roll-123",
            "/tmp/sample",
        ])
        proxy.setSourceModel(model)
        proxy.set_roll_filter(re.compile(r"roll-\d+", re.IGNORECASE))

        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertFalse(proxy.filterAcceptsRow(1, QModelIndex()))

    def test_directory_proxy_keeps_ignored_folders_hidden_when_regex_matches(self):
        proxy = DirectorySortFilterProxyModel()
        proxy.excluded_folders = ["Roll-123"]
        model = FakeDirectoryModel(["/tmp/Roll-123"])
        proxy.setSourceModel(model)
        proxy.set_roll_filter(re.compile(r"roll-\d+", re.IGNORECASE))

        self.assertFalse(proxy.filterAcceptsRow(0, QModelIndex()))

    def test_directory_proxy_does_not_apply_roll_regex_to_root_directory(self):
        proxy = DirectorySortFilterProxyModel()
        proxy.excluded_folders = []
        model = FakeDirectoryModel(["/tmp/root"])
        proxy.setSourceModel(model)
        proxy.set_root_directory("/tmp/root")
        proxy.set_roll_filter(re.compile(r"roll-\d+", re.IGNORECASE))

        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))

    def test_directory_proxy_does_not_apply_roll_regex_to_root_ancestors(self):
        proxy = DirectorySortFilterProxyModel()
        proxy.excluded_folders = []
        model = FakeDirectoryModel(["/tmp"])
        proxy.setSourceModel(model)
        proxy.set_root_directory("/tmp/root")
        proxy.set_roll_filter(re.compile(r"roll-\d+", re.IGNORECASE))

        self.assertTrue(proxy.filterAcceptsRow(0, QModelIndex()))

    def test_set_roll_filter_reapplies_root_index_after_proxy_invalidation(self):
        view = DirectoryView()
        try:
            view._root_directory = "/tmp/root"
            view._apply_root_index = MagicMock(return_value=True)

            view.set_roll_filter("roll", re.compile("roll", re.IGNORECASE))

            view._apply_root_index.assert_called_once()
        finally:
            view.close()

    def test_set_roll_filter_does_not_emit_directory_contents_changed_for_proxy_rows(self):
        view = DirectoryView()
        try:
            proxy = DirectorySortFilterProxyModel()
            proxy.excluded_folders = []
            proxy.setSourceModel(FakeDirectoryModel([
                "/tmp/Roll-123",
                "/tmp/sample",
                "/tmp/Other",
            ]))
            proxy.rowsRemoved.connect(view.on_rows_removed)
            view.proxy_model = proxy
            view._apply_root_index = MagicMock(return_value=True)
            emitted = []
            view.directory_contents_changed.connect(lambda: emitted.append(True))

            self.assertEqual(proxy.rowCount(), 3)
            view.set_roll_filter("roll", re.compile("roll", re.IGNORECASE))
            QApplication.processEvents()

            self.assertEqual(proxy.rowCount(), 1)
            self.assertEqual(emitted, [])
        finally:
            view.close()

    def test_regex_filter_line_edit_keeps_previous_valid_filter_on_invalid_regex(self):
        widget = RegexFilterLineEdit(_("ROLL_FILTER_PLACEHOLDER"))
        try:
            emitted = []
            widget.filter_changed.connect(lambda pattern, regex: emitted.append((pattern, regex)))

            widget.setText("roll")
            widget.apply_filter_text()
            widget.setText("[")
            widget.apply_filter_text()

            self.assertEqual([pattern for pattern, _ in emitted], ["roll"])
            self.assertEqual(widget.active_pattern, "roll")
            self.assertTrue(widget.toolTip())
        finally:
            widget.close()

    def test_regex_filter_line_edit_debounces_rapid_typing(self):
        from PySide6.QtTest import QTest

        widget = RegexFilterLineEdit(_("ROLL_FILTER_PLACEHOLDER"), debounce_ms=200)
        try:
            emitted = []
            widget.filter_changed.connect(lambda pattern, regex: emitted.append(pattern))

            widget.setText("ro")
            widget.setText("roll")
            QTest.qWait(250)

            self.assertEqual(emitted, ["roll"])
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
