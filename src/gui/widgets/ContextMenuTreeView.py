from PySide6.QtWidgets import (
    QTreeView,
    QMenu,
    QInputDialog,
    QMessageBox,
    QFileSystemModel
)
from PySide6.QtCore import QDir, Signal, Qt, QFile, QModelIndex, QFileInfo, QSortFilterProxyModel
from PySide6.QtGui import QAction

class ContextMenuTreeView(QTreeView):
    rootIndexChanged = Signal()

    def __init__(self, model: QFileSystemModel | QSortFilterProxyModel):
        super().__init__()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)
        self.setModel(model)

        if isinstance(model, QSortFilterProxyModel): # Ensure compatibility with QSortFilterProxyModel
            self._proxy_model = model
            self._model = model.sourceModel()
        else:
            self._proxy_model = None
            self._model = model

    def open_context_menu(self, position):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        context_menu = QMenu()
        rename_action = QAction("Rename", self)
        delete_action = QAction("Delete", self)

        rename_action.triggered.connect(lambda: self.rename_file(indexes[0]))
        delete_action.triggered.connect(lambda: self.delete_file(indexes[0]))

        context_menu.addAction(rename_action)
        context_menu.addAction(delete_action)

        context_menu.exec_(self.viewport().mapToGlobal(position))

    def rename_file(self, index: QModelIndex):
        if self._proxy_model:
            index = self._proxy_model.mapToSource(index)
        old_name = self._model.fileName(index)
        new_name, ok = QInputDialog.getText(self, "Rename File", "New Name:", text=old_name)

        if ok and new_name:
            old_path = self._model.filePath(index)
            new_path = self._model.filePath(index.parent()) + "/" + new_name

            if not QFile.rename(old_path, new_path):
                QMessageBox.warning(self, "Rename Failed", f"Could not rename {old_name} to {new_name}")

    def delete_file(self, index: QModelIndex):
        if self._proxy_model:
            index = self._proxy_model.mapToSource(index)
        file_path = self._model.filePath(index)
        file_info = QFileInfo(file_path)

        if file_info.isDir():
            dir = QDir(file_path)
            reply = QMessageBox.question(self, "Delete Folder", f"Are you sure you want to delete {file_path} and all its contents?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                if not dir.removeRecursively():
                    QMessageBox.warning(self, "Delete Failed", f"Could not delete folder {file_path}")
        else:
            reply = QMessageBox.question(self, "Delete File", f"Are you sure you want to delete {file_path}?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if not QFile.remove(file_path):
                    QMessageBox.warning(self, "Delete Failed", f"Could not delete file {file_path}")

    def setRootIndex(self, index):
        super().setRootIndex(index)
        self.rootIndexChanged.emit()
        self.setRootIsDecorated(False)