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
    QDateTime,
    QSortFilterProxyModel,
    Signal,
    QFileSystemWatcher,
    QItemSelectionModel
)
from settings import DEFAULT_ROLL_DIRECTORY
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
from utils.file_utils import open_in_file_explorer
import os
from datetime import datetime

CUSTOM_SORT_FILES_IN_DIRECTORY_LIMIT = 128

class DirectoryView(QWidget):
    root_directory_changed = Signal(str)
    directory_selected     = Signal(str)
    directory_contents_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the layout
        layout = QVBoxLayout(self)

        # Create the model and proxy
        self.model = CustomFileSystemModel()
        self.model.setRootPath(QDir.currentPath())
        # Only show directories
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)
        self.proxy_model = DirectorySortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self.treeView = ContextMenuTreeView(self.proxy_model)
        self.treeView.selectionModel().selectionChanged.connect(self.on_directory_selected)

        # Show only the first and modified date columns
        for i in range(1, self.model.columnCount()):
            if i != 3:  # Assuming column 3 is the "Date Modified" column
                self.treeView.setColumnHidden(i, True)

        self.treeView.setColumnWidth(0, 200)

        dir_path = QDir(QDir.homePath()).filePath(DEFAULT_ROLL_DIRECTORY)

        if QDir().mkpath(dir_path):
            self.treeView.setRootIndex(self.proxy_model.mapFromSource(self.model.index(dir_path)))
        else:
            print("Failed to create folder!")
            self.treeView.setRootIndex(self.proxy_model.mapFromSource(self.model.index(QDir.currentPath())))

        self.model.directoryLoaded.connect(self.select_first_directory)

        # Sort the folders by custom modified date
        self.treeView.setSortingEnabled(True)
        self.treeView.header().setSortIndicatorShown(True)
        self.treeView.sortByColumn(3, Qt.SortOrder.DescendingOrder)

        self.openDirButton = QPushButton("Open in file explorer")
        self.openDirButton.clicked.connect(self.open_directory)

        # Create the button
        self.changeDirButton = QPushButton("Change directory")
        self.changeDirButton.clicked.connect(self.change_directory)

        # Add widgets to the layout
        layout.addWidget(self.treeView)
        layout.addWidget(self.openDirButton)
        layout.addWidget(self.changeDirButton)

        # Setup the QFileSystemWatcher
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_directory_changed)
        self.watcher.fileChanged.connect(self.on_file_changed)

        # Watch the initial root directory
        root_index = self.proxy_model.mapToSource(self.treeView.rootIndex())
        root_directory = self.model.filePath(root_index)
        self.watch_directory_and_subdirs(root_directory)

    def watch_directory_and_subdirs(self, directory):
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

    def select_first_directory(self):
        # Get the first child of the current root index
        root_index = self.treeView.rootIndex()
        if root_index.isValid():
            first_child = self.treeView.model().index(0, 0, root_index)
            if first_child.isValid():
                self.treeView.selectionModel().select(
                    first_child,
                    QItemSelectionModel.SelectionFlag.Select |
                    QItemSelectionModel.SelectionFlag.Current |
                    QItemSelectionModel.SelectionFlag.Rows
                )
                # Emit the signal for the newly selected directory
                self.on_directory_selected(self.treeView.selectionModel().selection(), None)

    def open_directory(self):
        current_index = self.proxy_model.mapToSource(self.treeView.rootIndex())
        current_directory = self.model.filePath(current_index)
        open_in_file_explorer(current_directory)

    def change_directory(self):
        current_index = self.proxy_model.mapToSource(self.treeView.rootIndex())
        current_directory = self.model.filePath(current_index)
        # Open a dialog to select a directory
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", current_directory)

        if directory:
            # Update the root index of the tree view to reflect the new directory
            self.treeView.setRootIndex(self.proxy_model.mapFromSource(self.model.index(directory)))
            self.root_directory_changed.emit(directory)
            # Watch the new directory and its subdirectories
            self.watch_directory_and_subdirs(directory)

    def on_directory_selected(self, selected, deselected):
        indexes = selected.indexes()
        if len(indexes):
            selected = indexes[0]
            source_index = self.proxy_model.mapToSource(selected)
            file_path = self.model.filePath(source_index)
            self.directory_selected.emit(file_path)

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
        self.model.invalidate_cache(directory_path)

        # Update the view for that directory (same logic as directory_changed)
        index = self.model.index(directory_path)
        if index.isValid():
            # The "Date Modified" column is 3
            top_left = self.proxy_model.mapFromSource(self.model.index(index.row(), 3, index.parent()))
            bottom_right = top_left
            self.proxy_model.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])
        self.directory_contents_changed.emit()

class CustomFileSystemModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.modified_date_cache = {}

    def data(self, index: QModelIndex, role: int):
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 3:
            file_path = self.filePath(index)
            # Check if cached
            if file_path not in self.modified_date_cache:
                latest_modified_date = self.get_latest_modified_date(file_path)
                if latest_modified_date:
                    self.modified_date_cache[file_path] = QDateTime(latest_modified_date)
            return self.modified_date_cache.get(file_path, super().data(index, role))
        return super().data(index, role)

    def get_latest_modified_date(self, directory_path):
        try:
            latest_date = None
            for root, _, files in os.walk(directory_path):
                if len(files) > CUSTOM_SORT_FILES_IN_DIRECTORY_LIMIT:
                    return None
                for file_name in files:
                    if '.prof' in file_name and file_name != "mean.prof":
                        file_path = os.path.join(root, file_name)
                        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if latest_date is None or file_modified > latest_date:
                            latest_date = file_modified
            return latest_date
        except Exception as e:
            print(f"Error while fetching latest modified date: {e}")
            return None

    def invalidate_cache(self, directory_path):
        """Remove the cached date for the given directory to force a recalculation."""
        if directory_path in self.modified_date_cache:
            del self.modified_date_cache[directory_path]

class DirectorySortFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex):
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole)

        if isinstance(left_data, QDateTime) and isinstance(right_data, QDateTime):
            return left_data < right_data
        return super().lessThan(left, right)
