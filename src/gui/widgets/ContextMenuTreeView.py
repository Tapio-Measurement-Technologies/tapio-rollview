from PySide6.QtWidgets import (
    QTreeView,
    QMenu,
    QMessageBox,
    QFileSystemModel,
    QLineEdit,
    QDialog,
    QVBoxLayout,
    QLabel,
    QDialogButtonBox
)
from PySide6.QtCore import QDir, Signal, Qt, QFile, QModelIndex, QFileInfo, QSortFilterProxyModel
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from utils.file_utils import open_in_file_explorer
from utils.translation import _
import os


class RenameDialog(QDialog):
    def __init__(self, parent, title, label, initial_text):
        super().__init__(parent)
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))

        self.line_edit = QLineEdit(initial_text)
        layout.addWidget(self.line_edit)

        # Highlight filename without extension if it has one
        if '.' in initial_text:
            last_dot = initial_text.rfind('.')
            self.line_edit.setSelection(0, last_dot)
        else:
            self.line_edit.selectAll()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text_value(self):
        return self.line_edit.text()

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

        # Add F2 shortcut for rename
        self.rename_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F2), self)
        self.rename_shortcut.activated.connect(self._rename_selected)
        self.rename_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def open_context_menu(self, position):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        context_menu = QMenu()
        open_action   = QAction(_("BUTTON_TEXT_OPEN_FILE_EXPLORER"), self)
        rename_action = QAction(_("BUTTON_TEXT_RENAME"), self)
        delete_action = QAction(_("BUTTON_TEXT_DELETE"), self)

        # Add F2 shortcut hint to rename action
        rename_action.setShortcut(QKeySequence("F2"))

        open_action.triggered.connect(lambda: self.open_file_explorer(indexes[0]))
        rename_action.triggered.connect(lambda: self.rename_file(indexes[0]))
        delete_action.triggered.connect(lambda: self.delete_file(indexes[0]))

        context_menu.addAction(open_action)
        context_menu.addAction(rename_action)
        context_menu.addAction(delete_action)

        context_menu.exec_(self.viewport().mapToGlobal(position))

    def open_file_explorer(self, index: QModelIndex):
        if self._proxy_model:
            index = self._proxy_model.mapToSource(index)
        file_path = self._model.filePath(index)
        file_info = QFileInfo(file_path)

        selected_path = None
        if not file_info.isDir():
            # If it's a file, select it and open its parent directory
            selected_path = file_path
            file_path = file_info.absolutePath()
        else:
            # If it's a directory, select it in its parent directory
            selected_path = file_path

        open_in_file_explorer(file_path, selected_path)

    def _rename_selected(self):
        """Rename the currently selected item when F2 is pressed."""
        indexes = self.selectedIndexes()
        if indexes:
            self.rename_file(indexes[0])

    def rename_file(self, index: QModelIndex):
        if self._proxy_model:
            index = self._proxy_model.mapToSource(index)
        old_name = self._model.fileName(index)

        dialog = RenameDialog(self, _("RENAME_DIALOG_TITLE"), f"{_('RENAME_DIALOG_NEW_NAME_TEXT')}:", old_name)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.text_value()
            if new_name and new_name != old_name:
                old_path = self._model.filePath(index)
                parent_path = self._model.filePath(index.parent())
                new_path = os.path.join(parent_path, new_name)

                if not QFile.rename(old_path, new_path):
                    QMessageBox.warning(self, _("RENAME_FAILED_MSGBOX_TITLE"), f"{_("RENAME_FAILED_MSGBOX_TEXT")} {old_name}")

    def delete_file(self, index: QModelIndex):
        if self._proxy_model:
            index = self._proxy_model.mapToSource(index)
        file_path = self._model.filePath(index)
        file_info = QFileInfo(file_path)

        if file_info.isDir():
            dir = QDir(file_path)
            reply = QMessageBox.question(self, _("DELETE_DIALOG_TITLE"), f"{_("DELETE_DIALOG_FOLDER_TEXT_1")} {file_path} {_("DELETE_DIALOG_FOLDER_TEXT_2")}?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                if not dir.removeRecursively():
                    QMessageBox.warning(self, _("DELETE_FAILED_MSGBOX_TITLE"), f"{_("DELETE_FAILED_MSGBOX_TEXT")} {file_path}")
        else:
            reply = QMessageBox.question(self, _("DELETE_DIALOG_TITLE"), f"{_("DELETE_DIALOG_FILE_TEXT")} {file_path}?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if not QFile.remove(file_path):
                    QMessageBox.warning(self, _("DELETE_FAILED_MSGBOX_TITLE"), f"{_("DELETE_FAILED_MSGBOX_TEXT")} {file_path}")

    def setRootIndex(self, index):
        super().setRootIndex(index)
        self.rootIndexChanged.emit()
        self.setRootIsDecorated(False)