from PySide6.QtWidgets import (
    QFileSystemModel,
    QFileDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    QDir,
    Qt,
    QModelIndex,
    QPersistentModelIndex,
    QDateTime,
    QSortFilterProxyModel,
    Signal,
    QFileSystemWatcher,
    QItemSelectionModel,
    QTimer,
    QSignalBlocker,
)
import settings
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
from gui.widgets.RegexFilterLineEdit import RegexFilterLineEdit
from utils.file_utils import open_in_file_explorer
from utils.translation import _
from gui.widgets.messagebox import show_error_msgbox
import os
from datetime import datetime

CUSTOM_SORT_FILES_IN_DIRECTORY_LIMIT = 128

selection_flags = (
    QItemSelectionModel.SelectionFlag.Clear |
    QItemSelectionModel.SelectionFlag.Select |
    QItemSelectionModel.SelectionFlag.Current |
    QItemSelectionModel.SelectionFlag.Rows
)

class DirectoryTreeView(ContextMenuTreeView):
    selectionCleared = Signal()

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and not index.isValid():
            self.selectionModel().clear()
            self.selectionModel().clearCurrentIndex()
            self.setCurrentIndex(QModelIndex())
            self.selectionCleared.emit()
            return

        super().mousePressEvent(event)


class DirectoryView(QWidget):
    root_directory_changed = Signal(str)
    directory_selected     = Signal(str)
    directory_contents_changed = Signal()
    roll_filter_changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_delete_parent = QPersistentModelIndex()
        self._pending_delete_row = None
        self._pending_focus_path = None
        self._pending_focus_active = False
        self._focus_restore_scheduled = False
        self._root_directory = None
        self._selected_directory_path = None
        self.active_roll_filter_pattern = ""
        self.active_roll_filter_regex = None
        self._suppress_directory_contents_signal = False

        # Set up the layout
        layout = QVBoxLayout(self)

        # Create the model and proxy
        self.model = CustomFileSystemModel()
        self.model.setRootPath(QDir.homePath())
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)
        self.model.directoryLoaded.connect(self.init_selection)
        self.model.fileRenamed.connect(self.on_directory_renamed)

        self.proxy_model = DirectorySortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self.treeView = DirectoryTreeView(self.proxy_model)
        self.treeView.set_empty_message(_("DIRECTORY_EMPTY_STATE_NO_FOLDERS"))
        self.treeView.selectionModel().currentChanged.connect(self.on_directory_selected)
        self.treeView.selectionCleared.connect(self.on_selection_cleared)
        self.treeView.deleteRequested.connect(self.on_delete_requested)
        # Sort the folders by custom modified date
        self.treeView.setSortingEnabled(True)
        self.treeView.header().setSortIndicatorShown(True)
        self.treeView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        # Disable expanding tree view items
        self.treeView.setItemsExpandable(False)
        self.treeView.setExpandsOnDoubleClick(False)
        self.treeView.setColumnWidth(0, 200)

        # Show only the first and modified date columns
        for i in range(1, self.model.columnCount()):
            if i != 3:  # Assuming column 3 is the "Date Modified" column
                self.treeView.setColumnHidden(i, True)

        self.rollFilterInput = RegexFilterLineEdit(_("FOLDER_FILTER_PLACEHOLDER"))
        self.rollFilterInput.filter_changed.connect(self.set_roll_filter)

        self.openDirButton = QPushButton(_("BUTTON_TEXT_OPEN_FILE_EXPLORER"))
        self.openDirButton.clicked.connect(self.open_directory_in_file_explorer)

        # Create the button
        self.changeDirButton = QPushButton(_("BUTTON_TEXT_CHANGE_DIRECTORY"))
        self.changeDirButton.clicked.connect(self.change_root_directory)

        # Add widgets to the layout
        layout.addWidget(self.rollFilterInput)
        layout.addWidget(self.treeView)
        layout.addWidget(self.openDirButton)
        layout.addWidget(self.changeDirButton)

        # Setup the QFileSystemWatcher
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_directory_changed)
        self.watcher.fileChanged.connect(self.on_file_changed)
        self.proxy_model.rowsRemoved.connect(self.on_rows_removed)
        self.proxy_model.rowsAboutToBeInserted.connect(self.on_rows_about_to_be_inserted)
        self.proxy_model.rowsInserted.connect(self.on_rows_inserted)
        self.proxy_model.layoutAboutToBeChanged.connect(self.on_layout_about_to_change)
        self.proxy_model.layoutChanged.connect(self.on_layout_changed)

    @staticmethod
    def get_row_to_select_after_delete(deleted_row, row_count):
        if row_count <= 1:
            return None
        if deleted_row > 0:
            return deleted_row - 1
        return 0

    def watch_directory_and_subdirs(self, directory):
        # Validate that the directory path exists and is a directory
        if not directory or not os.path.exists(directory) or not os.path.isdir(directory):
            print(f"Invalid directory path provided to watch_directory_and_subdirs: '{directory}'")
            return

        try:
            # Clear previous watchers
            if len(self.watcher.directories()):
                self.watcher.removePaths(self.watcher.directories())
            if len(self.watcher.files()):
                self.watcher.removePaths(self.watcher.files())

            # Add the main directory
            self.watcher.addPath(directory)

            # Add all immediate subdirectories
            for entry in os.scandir(directory):
                if entry.is_dir():
                    self.watcher.addPath(entry.path)
        except PermissionError:
            show_error_msgbox(
                _("ERROR_MSGBOX_TEXT_PERMISSION_DENIED").format(directory=directory),
                _("ERROR_MSGBOX_TITLE")
            )
        except OSError as e:
            show_error_msgbox(
                _("ERROR_MSGBOX_TEXT_OPERATION_FAILED").format(error=str(e)),
                _("ERROR_MSGBOX_TITLE")
            )

    def select_first_directory(self, set_focus=True):
        # Get the first child of the current root index
        root_index = self.treeView.rootIndex()
        if not root_index.isValid():
            return

        first_child = self.treeView.model().index(0, 0, root_index)
        if not first_child.isValid():
            return

        if set_focus:
            self.treeView.setFocus(Qt.FocusReason.OtherFocusReason)
        self.treeView.setCurrentIndex(first_child)
        self.treeView.selectionModel().setCurrentIndex(first_child, selection_flags)
        self.treeView.scrollTo(first_child)

    def _apply_root_index(self):
        if not self._root_directory:
            return False
        self.proxy_model.set_root_directory(self._root_directory)
        root_index = self.proxy_model.mapFromSource(self.model.index(self._root_directory))
        if not root_index.isValid():
            return False
        self.treeView.setRootIndex(root_index)
        return True

    def _note_directory_load_failed(self, directory):
        print(_("ERROR_MSGBOX_TEXT_DIRECTORY_LOAD_FAILED").format(directory=directory))

    def _clear_current_selection(self, clear_logical_selection=False):
        selection_model = self.treeView.selectionModel()
        selection_model.clear()
        selection_model.clearCurrentIndex()
        self.treeView.setCurrentIndex(QModelIndex())
        if clear_logical_selection:
            self._selected_directory_path = None

    def _clear_pending_focus_restore(self):
        self._pending_focus_path = None
        self._pending_focus_active = False
        self._focus_restore_scheduled = False

    def set_roll_filter(self, pattern, compiled_regex):
        selected_path = self.get_selected_directory_path()
        self.active_roll_filter_pattern = pattern
        self.active_roll_filter_regex = compiled_regex
        self._suppress_directory_contents_signal = True
        selection_blocker = QSignalBlocker(self.treeView.selectionModel())
        try:
            self.proxy_model.set_roll_filter(compiled_regex)
            self._apply_root_index()
            self._selected_directory_path = selected_path
            self._sync_selection_after_filter()
        finally:
            self._suppress_directory_contents_signal = False
            del selection_blocker
        self.roll_filter_changed.emit(pattern, compiled_regex)

    def init_selection(self):
        if not self.treeView.rootIndex().isValid():
            self._apply_root_index()
        if not self.get_selected_directory_path() and self.treeView.rootIndex().isValid():
            self.select_first_directory()

    def select_directory_by_path(self, path, warn=True):
        index = self.proxy_model.mapFromSource(self.model.index(path))
        if index.isValid():
            self._selected_directory_path = path
            self.treeView.setCurrentIndex(index)
            self.treeView.selectionModel().setCurrentIndex(index, selection_flags)
            self.treeView.scrollTo(index)
            return True
        if warn:
            print(f"Invalid index provided to select_directory_by_path: '{path}'")
        return False

    def open_directory_in_file_explorer(self):
        current_index = self.proxy_model.mapToSource(self.treeView.rootIndex())
        current_directory = self.model.filePath(current_index)

        open_in_file_explorer(current_directory, self.get_selected_directory_path())

    def change_root_directory(self, directory = None):
        if not directory:
            current_index = self.proxy_model.mapToSource(self.treeView.rootIndex())
            current_directory = self.model.filePath(current_index)
            # Open a dialog to select a directory
            directory = QFileDialog.getExistingDirectory(self, _("CHANGE_DIRECTORY_DIALOG_TITLE"), current_directory)

        if directory:
            try:
                # Validate that the directory path exists and is a directory
                if not os.path.exists(directory):
                    show_error_msgbox(
                        _("ERROR_MSGBOX_TEXT_DIRECTORY_NOT_FOUND").format(directory=directory),
                        _("ERROR_MSGBOX_TITLE")
                    )
                    return

                if not os.path.isdir(directory):
                    show_error_msgbox(
                        _("ERROR_MSGBOX_TEXT_NOT_A_DIRECTORY").format(path=directory),
                        _("ERROR_MSGBOX_TITLE")
                    )
                    return

                # Update the root index of the tree view to reflect the new directory.
                # QFileSystemModel can resolve indexes asynchronously, so an
                # initially invalid index is not a blocking user-facing error.
                self._root_directory = directory
                self._clear_current_selection(clear_logical_selection=True)
                self._clear_pending_focus_restore()
                self.model.setRootPath(directory)
                self.proxy_model.set_root_directory(directory)
                root_index = self.proxy_model.mapFromSource(self.model.index(directory))
                root_index_valid = root_index.isValid()
                if root_index_valid:
                    self.treeView.setRootIndex(root_index)
                else:
                    self._note_directory_load_failed(directory)

                self.root_directory_changed.emit(directory)
                # Watch the new directory and its subdirectories
                self.watch_directory_and_subdirs(directory)

                # Initially select the first directory in the new root
                if root_index_valid:
                    self.select_first_directory()
            except PermissionError:
                show_error_msgbox(
                    _("ERROR_MSGBOX_TEXT_PERMISSION_DENIED").format(directory=directory),
                    _("ERROR_MSGBOX_TITLE")
                )
            except OSError as e:
                show_error_msgbox(
                    _("ERROR_MSGBOX_TEXT_OPERATION_FAILED").format(error=str(e)),
                    _("ERROR_MSGBOX_TITLE")
                )

    def on_directory_selected(self, current, previous):
        if not current.isValid():
            return

        source_index = self.proxy_model.mapToSource(current)
        if not source_index.isValid():
            return

        file_path = self.model.filePath(source_index)
        self._selected_directory_path = file_path
        self.directory_selected.emit(file_path)

    def on_selection_cleared(self):
        if self._root_directory and os.path.isdir(self._root_directory):
            self._selected_directory_path = self._root_directory
            self.directory_selected.emit(self._root_directory)

    def on_directory_renamed(self, path, old_name, new_name):
        old_path = os.path.join(path, old_name)
        new_path = os.path.join(path, new_name)
        if not os.path.isdir(new_path):
            return

        self.model.invalidate_cache(old_path)
        self.model.invalidate_cache(new_path)
        if self._root_directory:
            self.watch_directory_and_subdirs(self._root_directory)

        current_path = self.get_selected_directory_path()
        if current_path in (old_path, new_path):
            self._selected_directory_path = new_path
            self.directory_selected.emit(new_path)

    def on_delete_requested(self, index):
        proxy_index = index.siblingAtColumn(0)
        target_row = self.get_row_to_select_after_delete(
            proxy_index.row(),
            self.proxy_model.rowCount(proxy_index.parent()),
        )

        if target_row is None:
            self._pending_delete_parent = QPersistentModelIndex()
            self._pending_delete_row = None
            return

        self._pending_delete_parent = QPersistentModelIndex(proxy_index.parent())
        self._pending_delete_row = target_row

    def on_rows_removed(self, parent, first, last):
        if self._suppress_directory_contents_signal:
            return
        if self._pending_delete_row is None:
            QTimer.singleShot(0, lambda: self.directory_contents_changed.emit())
            return
        QTimer.singleShot(0, self._restore_selection_after_delete)

    def _get_visible_selected_directory_path(self):
        selection_model = self.treeView.selectionModel()
        selected_indexes = selection_model.selectedRows(0)
        selected_index = selected_indexes[0] if selected_indexes else selection_model.currentIndex()
        if not selected_index.isValid():
            return None

        source_index = self.proxy_model.mapToSource(selected_index)
        if not source_index.isValid():
            return None

        selected_path = self.model.filePath(source_index)
        if (
            self._root_directory
            and not self._path_is_within_directory(selected_path, self._root_directory)
        ):
            return None

        return selected_path

    def _is_selectable_directory_path(self, path):
        return (
            path
            and os.path.isdir(path)
            and (
                not self._root_directory
                or self._path_is_within_directory(path, self._root_directory)
            )
        )

    def get_selected_directory_path(self):
        if self._is_selectable_directory_path(self._selected_directory_path):
            return self._selected_directory_path
        self._selected_directory_path = None

        selected_path = self._get_visible_selected_directory_path()
        if selected_path:
            self._selected_directory_path = selected_path
        return selected_path

    def preserve_current_directory_focus(self):
        if self._suppress_directory_contents_signal:
            return
        self._pending_focus_path = self.get_selected_directory_path()
        self._pending_focus_active = self.treeView.hasFocus()

    def on_rows_about_to_be_inserted(self, parent, first, last):
        self.preserve_current_directory_focus()

    def on_rows_inserted(self, parent, first, last):
        self.refresh_inserted_rows(parent, first, last)
        self.schedule_focus_restore()

    def refresh_inserted_rows(self, parent, first, last):
        if first > last:
            return

        for row in range(first, last + 1):
            source_index = self.proxy_model.mapToSource(self.proxy_model.index(row, 3, parent))
            if not source_index.isValid():
                continue
            self.model.invalidate_cache(self.model.filePath(source_index))

        top_left = self.proxy_model.index(first, 3, parent)
        bottom_right = self.proxy_model.index(last, 3, parent)
        if top_left.isValid() and bottom_right.isValid():
            self.proxy_model.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

        sort_column = self.treeView.header().sortIndicatorSection()
        sort_order = self.treeView.header().sortIndicatorOrder()
        self.proxy_model.sort(sort_column, sort_order)

    def on_layout_about_to_change(self):
        self.preserve_current_directory_focus()

    def on_layout_changed(self):
        self.schedule_focus_restore()

    def schedule_focus_restore(self):
        if self._suppress_directory_contents_signal:
            return
        if self._focus_restore_scheduled or not self._pending_focus_path:
            return

        self._focus_restore_scheduled = True
        QTimer.singleShot(0, self._restore_focus_after_model_change)

    def _restore_focus_after_model_change(self):
        self._focus_restore_scheduled = False

        focus_path = self._pending_focus_path
        self._pending_focus_path = None
        focus_active = self._pending_focus_active
        self._pending_focus_active = False
        if not focus_path or not os.path.isdir(focus_path):
            return

        current_path = self._get_visible_selected_directory_path()
        if current_path == focus_path:
            if focus_active:
                self.treeView.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        if not self.select_directory_by_path(focus_path, warn=False):
            if self.active_roll_filter_regex:
                self._clear_current_selection()
            else:
                self.select_first_directory(set_focus=False)
        if focus_active:
            self.treeView.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync_selection_after_filter(self):
        selected_path = self.get_selected_directory_path()
        if not selected_path:
            self._clear_current_selection()
            return
        if self._root_directory and self._same_path(selected_path, self._root_directory):
            self._clear_current_selection()
            return

        if not self.select_directory_by_path(selected_path, warn=False):
            self._clear_current_selection()

    def _restore_selection_after_delete(self):
        if self._pending_delete_row is None:
            return

        parent = QModelIndex(self._pending_delete_parent)
        row_count = self.proxy_model.rowCount(parent)
        if row_count <= 0:
            self._pending_delete_parent = QPersistentModelIndex()
            self._pending_delete_row = None
            self.directory_contents_changed.emit()
            return

        target_row = min(self._pending_delete_row, row_count - 1)
        target_index = self.proxy_model.index(target_row, 0, parent)
        if target_index.isValid():
            self.treeView.setCurrentIndex(target_index)
            self.treeView.selectionModel().setCurrentIndex(target_index, selection_flags)
            self.treeView.scrollTo(target_index)

        self._pending_delete_parent = QPersistentModelIndex()
        self._pending_delete_row = None
        self.directory_contents_changed.emit()

    def on_directory_changed(self, path):
        # A directory changed event occurred
        # Invalidate cache for this directory in the model
        self.model.invalidate_cache(path)

        # Since data might have changed, force the view to update
        # We'll find the directory index and emit dataChanged accordingly
        index = self.model.index(path)
        if index.isValid():
            # The "Date Modified" column is 3
            top_left = self.proxy_model.mapFromSource(self.model.index(index.row(), 3, index.parent()))
            bottom_right = top_left
            self.proxy_model.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])
        self.directory_contents_changed.emit()

    def on_file_changed(self, path):
        # A specific file changed event occurred
        # Determine its parent directory and invalidate cache
        directory_path = os.path.dirname(path)
        self.on_directory_changed(directory_path)

    @staticmethod
    def _normalized_path_key(path):
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))

    @classmethod
    def _same_path(cls, first_path, second_path):
        return cls._normalized_path_key(first_path) == cls._normalized_path_key(second_path)

    @classmethod
    def _path_is_within_directory(cls, path, directory):
        if not path or not directory:
            return False

        try:
            path_abs = os.path.abspath(path)
            directory_abs = os.path.abspath(directory)
            common_path = os.path.commonpath([path_abs, directory_abs])
        except (OSError, ValueError):
            return False

        return cls._same_path(common_path, directory_abs)

    def _directory_date_refresh_paths(self, directory_paths):
        refresh_paths = []
        seen = set()
        root_directory = self._root_directory

        for path in directory_paths or []:
            if not path:
                continue

            current_path = os.path.abspath(path)
            if os.path.isfile(current_path):
                current_path = os.path.dirname(current_path)
            if not os.path.isdir(current_path):
                continue

            while current_path:
                key = self._normalized_path_key(current_path)
                if key not in seen:
                    seen.add(key)
                    refresh_paths.append(current_path)

                if not root_directory or self._same_path(current_path, root_directory):
                    break

                parent_path = os.path.dirname(current_path)
                if parent_path == current_path:
                    break

                if root_directory and not self._path_is_within_directory(parent_path, root_directory):
                    break

                current_path = parent_path

        return refresh_paths

    def _emit_directory_date_changed(self, directory_path):
        source_index = self.model.index(directory_path)
        if not source_index.isValid():
            return

        source_date_index = self.model.index(source_index.row(), 3, source_index.parent())
        if not source_date_index.isValid():
            return

        proxy_date_index = self.proxy_model.mapFromSource(source_date_index)
        if not proxy_date_index.isValid():
            return

        self.proxy_model.dataChanged.emit(
            proxy_date_index,
            proxy_date_index,
            [Qt.ItemDataRole.DisplayRole],
        )

    def refresh_directory_dates(self, directory_paths):
        refresh_paths = self._directory_date_refresh_paths(directory_paths)
        if not refresh_paths:
            return

        self.preserve_current_directory_focus()

        for directory_path in refresh_paths:
            self.model.invalidate_cache(directory_path)
            self._emit_directory_date_changed(directory_path)

        if self._root_directory:
            self.watch_directory_and_subdirs(self._root_directory)

        sort_column = self.treeView.header().sortIndicatorSection()
        sort_order = self.treeView.header().sortIndicatorOrder()
        self.proxy_model.sort(sort_column, sort_order)
        self.schedule_focus_restore()

class CustomFileSystemModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.modified_date_cache = {}

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            match section:
                case 0:
                    return _("TREEVIEW_HEADER_NAME")
                case 3:
                    return _("TREEVIEW_HEADER_DATE_MODIFIED")
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int):
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 3:
            file_path = self.filePath(index)
            # Check if cached
            if file_path not in self.modified_date_cache:
                latest_modified_date = self.get_latest_modified_date(file_path)
                if latest_modified_date:
                    self.modified_date_cache[file_path] = QDateTime(latest_modified_date)
                else:
                    # No custom date available, get the directory's own modification time
                    try:
                        dir_mtime = os.path.getmtime(file_path)
                        self.modified_date_cache[file_path] = QDateTime(datetime.fromtimestamp(dir_mtime))
                    except (OSError, PermissionError, ValueError):
                        # Handle problematic paths (root drives, special system paths, etc.)
                        # Return empty QDateTime for paths that cannot be accessed
                        self.modified_date_cache[file_path] = QDateTime()
            return self.modified_date_cache.get(file_path)
        return super().data(index, role)

    def get_latest_modified_date(self, directory_path):
        # Validate that the directory path exists and is a directory
        if not directory_path or not os.path.exists(directory_path) or not os.path.isdir(directory_path):
            return None

        try:
            latest_date = None
            for root, _, files in os.walk(directory_path):
                if len(files) > CUSTOM_SORT_FILES_IN_DIRECTORY_LIMIT:
                    return None
                for file_name in files:
                    file_name_lower = file_name.lower()
                    if file_name_lower.endswith('.prof') and file_name_lower != "mean.prof":
                        file_path = os.path.join(root, file_name)
                        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if latest_date is None or file_modified > latest_date:
                            latest_date = file_modified
            return latest_date
        except PermissionError:
            # Silently handle permission errors for individual directories
            # This is common when traversing directory trees
            return None
        except OSError:
            # Silently handle other OS errors (file deleted, etc.)
            # These are not critical for display purposes
            return None

    def invalidate_cache(self, directory_path):
        """Remove the cached date for the given directory to force a recalculation."""
        if directory_path in self.modified_date_cache:
            del self.modified_date_cache[directory_path]

class DirectorySortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Define folders to exclude
        self.excluded_folders = settings.IGNORE_FOLDERS
        self.roll_filter_regex = None
        self.root_directory = None

    def set_roll_filter(self, roll_filter_regex):
        self.roll_filter_regex = roll_filter_regex
        self.invalidateFilter()

    def set_root_directory(self, root_directory):
        if self.root_directory == root_directory:
            return
        self.root_directory = root_directory
        self.invalidateFilter()

    def is_root_or_root_ancestor(self, file_path):
        if not self.root_directory:
            return False

        try:
            normalized_path = os.path.normcase(os.path.abspath(file_path))
            normalized_root = os.path.normcase(os.path.abspath(self.root_directory))
            return (
                normalized_path == normalized_root
                or os.path.commonpath([normalized_path, normalized_root]) == normalized_path
            )
        except ValueError:
            return False

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        index = source_model.index(source_row, 0, source_parent)
        file_path = source_model.filePath(index)
        dir_name = os.path.basename(file_path)

        if self.is_root_or_root_ancestor(file_path):
            return super().filterAcceptsRow(source_row, source_parent)

        # Skip excluded folders
        if dir_name in self.excluded_folders:
            return False

        if self.roll_filter_regex and not self.roll_filter_regex.search(dir_name):
            return False

        return super().filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left: QModelIndex, right: QModelIndex):
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole)

        # Both should be QDateTime objects, so we can compare them directly
        if isinstance(left_data, QDateTime) and isinstance(right_data, QDateTime):
            return left_data < right_data

        # Fallback for any unexpected cases
        return super().lessThan(left, right)
