from PySide6.QtWidgets import (
    QFileSystemModel,
    QFileDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDir, Qt
from settings import DEFAULT_ROLL_DIRECTORY
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView

class DirectoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the layout
        layout = QVBoxLayout(self)

        # Create the TreeView
        self.model = QFileSystemModel()
        self.treeView = ContextMenuTreeView(self.model)
        self.model.setRootPath(QDir.rootPath())

        # Only show directories
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)

        # Hide all columns except the first one
        for i in range(1, self.model.columnCount()):
            self.treeView.setColumnHidden(i, True)

        dir_path = QDir(QDir.homePath()).filePath(DEFAULT_ROLL_DIRECTORY)

        if QDir().mkpath(dir_path):
            self.treeView.setRootIndex(self.model.index(dir_path))
        else:
            print("Failed to create folder!")
            self.treeView.setRootIndex(self.model.index(QDir.homePath()))

        # Sort the folders by modified date
        self.model.sort(3, Qt.SortOrder.DescendingOrder)

        # Create the button
        self.changeDirButton = QPushButton("Change Directory")
        self.changeDirButton.clicked.connect(self.change_directory)

        # Add widgets to the layout
        layout.addWidget(self.treeView)
        layout.addWidget(self.changeDirButton)

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