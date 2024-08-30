from PySide6.QtWidgets import (
    QFileSystemModel,
    QFileDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDir, Qt, QModelIndex, QDateTime
from settings import DEFAULT_ROLL_DIRECTORY
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
from utils.file_utils import open_in_file_explorer
import os
from datetime import datetime

class DirectoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the layout
        layout = QVBoxLayout(self)

        # Create the TreeView
        self.model = CustomFileSystemModel()
        self.treeView = ContextMenuTreeView(self.model)
        self.model.setRootPath(QDir.rootPath())

        # Only show directories
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)

        # Show only the first and modified date columns
        for i in range(1, self.model.columnCount()):
            if i != 3:  # Assuming column 3 is the "Date Modified" column
                self.treeView.setColumnHidden(i, True)

        self.treeView.setColumnWidth(0, 200)

        dir_path = QDir(QDir.homePath()).filePath(DEFAULT_ROLL_DIRECTORY)

        if QDir().mkpath(dir_path):
            self.treeView.setRootIndex(self.model.index(dir_path))
        else:
            print("Failed to create folder!")
            self.treeView.setRootIndex(self.model.index(QDir.homePath()))

        # Sort the folders by custom modified date
        self.model.sort(3, Qt.SortOrder.DescendingOrder)

        self.openDirButton = QPushButton("Open in file explorer")
        self.openDirButton.clicked.connect(self.open_directory)

        # Create the button
        self.changeDirButton = QPushButton("Change directory")
        self.changeDirButton.clicked.connect(self.change_directory)

        # Add widgets to the layout
        layout.addWidget(self.treeView)
        layout.addWidget(self.openDirButton)
        layout.addWidget(self.changeDirButton)

    def open_directory(self):
        current_index = self.treeView.rootIndex()
        current_directory = self.model.filePath(current_index)
        open_in_file_explorer(current_directory)

    def change_directory(self):
        current_index = self.treeView.rootIndex()
        current_directory = self.model.filePath(current_index)
        # Open a dialog to select a directory
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", current_directory)

        if directory:
            # Update the root index of the tree view to reflect the new directory
            self.treeView.setRootIndex(self.model.index(directory))
            # Reapply the sorting
            self.model.sort(3, Qt.SortOrder.DescendingOrder)

class CustomFileSystemModel(QFileSystemModel):
    def data(self, index: QModelIndex, role: int):
        # Use the standard data method for most roles
        if role == Qt.DisplayRole and index.column() == 3:  # Assuming column 3 is "Date Modified"
            file_path = self.filePath(index)
            # Calculate the latest modified date for this directory
            latest_modified_date = self.get_latest_modified_date(file_path)
            if latest_modified_date:
                return QDateTime(latest_modified_date)
        # Fall back to the default behavior
        return super().data(index, role)

    def get_latest_modified_date(self, directory_path):
        """Returns the latest modified date of the files within a directory."""
        try:
            latest_date = None
            for root, _, files in os.walk(directory_path):
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
