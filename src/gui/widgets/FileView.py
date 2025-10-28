from PySide6.QtWidgets import QFileSystemModel, QWidget, QVBoxLayout
from PySide6.QtCore import QDir, Qt, QSortFilterProxyModel, Signal, QModelIndex, QPersistentModelIndex
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
from utils.translation import _
from utils import preferences
import settings
import store
import os

PROF_FILE_HEADER_SIZE = 128

class CustomFilterProxyModel(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row, source_parent):
        index = self.sourceModel().index(source_row, 0, source_parent)
        file_name = self.sourceModel().fileName(index)
        if file_name == "mean.prof":
            return False
        return super().filterAcceptsRow(source_row, source_parent)

class CustomFileSystemModel(QFileSystemModel):
    def columnCount(self, parent=QModelIndex()):
        # Original columns: Name(0), Size(1), Type(2), Date Modified(3)
        # We add two columns: Profile length(4), Hidden state(5)
        return super().columnCount(parent) + 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        column = index.column()

        # Handle original timestamp column
        if column == 3 and role == Qt.ItemDataRole.DisplayRole:
            if settings.CUSTOM_DATE_FORMAT:
                file_info = self.fileInfo(index)
                timestamp = file_info.lastModified()
                py_datetime = timestamp.toPython()
                formatted_timestamp = py_datetime.strftime(settings.CUSTOM_DATE_FORMAT)
                return formatted_timestamp
            else:
                return super().data(index, role)

        # Profile length column
        if column == 4:
            if role == Qt.ItemDataRole.DisplayRole:
                file_info = self.fileInfo(index)
                file_path = file_info.filePath()
                profile = store.get_profile_by_filename(file_path)
                if not profile:
                    return "--"
                prof_len = profile.profile_length
                unit_info = preferences.get_distance_unit_info()
                prof_len_converted = prof_len * unit_info.conversion_factor
                return f"{prof_len_converted:.2f} {unit_info.unit}"

        # Hidden state checkbox column
        if column == 5:
            file_info = self.fileInfo(index)
            file_path = file_info.filePath()
            profile = store.get_profile_by_filename(file_path)

            if role == Qt.ItemDataRole.CheckStateRole:
                if not profile:
                    return Qt.CheckState.Checked
                # Checked means show => if hidden = False, Checked; if hidden = True, Unchecked
                return Qt.CheckState.Checked if not profile.hidden else Qt.CheckState.Unchecked
            elif role == Qt.ItemDataRole.DisplayRole:
                return ""

        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False

        column = index.column()

        # Handle checkbox toggling: checked means show (hidden = False)
        if column == 5 and role == Qt.ItemDataRole.CheckStateRole:
            file_info = self.fileInfo(index)
            file_path = file_info.filePath()
            profile = store.get_profile_by_filename(file_path)
            # If checkbox is checked => show => hidden = False
            # If checkbox is unchecked => do not show => hidden = True
            hidden = (value == Qt.CheckState.Unchecked.value)
            profile.hidden = hidden
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True

        return super().setData(index, value, role)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            match section:
                case 0:
                    return _("TREEVIEW_HEADER_NAME")
                case 1:
                    return _("TREEVIEW_HEADER_SIZE")
                case 3:
                    return _("TREEVIEW_HEADER_DATE_MODIFIED")
                case 4:
                    return _("TREEVIEW_HEADER_PROFILE_LENGTH")
                case 5:
                    return ""
        return super().headerData(section, orientation, role)

    def flags(self, index):
        fl = super().flags(index)
        if index.column() == 5:
            # Make the 'Hidden' column checkable
            fl |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        return fl


class FileTreeView(ContextMenuTreeView):
    selectionCleared = Signal()

    def __init__(self, model) -> None:
        super().__init__(model)
        self.setMaximumHeight(400)
        self.last_index = None

    # Override mousePressEvent for deselecting items
    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if (event.button() == Qt.MouseButton.LeftButton and
            self.last_index == index) or not index.isValid():
            # If the same row is clicked again or click is outside rows, deselect it
            self.selectionModel().clearSelection()
            self.selectionCleared.emit()
            self.last_index = None
        else:
            super().mousePressEvent(event)
            self.last_index = index

class FileView(QWidget):
    file_selected = Signal(str)
    profile_state_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMaximumHeight(400)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(5, 0, 10, 0)

        self.model = CustomFileSystemModel()
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.Files)
        self.model.setNameFilters(["*.prof"])  # Set the filter for .prof files
        self.model.setNameFilterDisables(False)  # Enable the name filter

        self.proxy_model = CustomFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self.view = FileTreeView(self.proxy_model)
        self.view.setSortingEnabled(True)
        self.view.header().setSortIndicatorShown(True)
        self.view.sortByColumn(3, Qt.SortOrder.DescendingOrder)

        self.view.selectionModel().selectionChanged.connect(self.on_file_selected)
        self.view.selectionCleared.connect(self.on_selection_cleared)

        # Hide file type column
        for i in range(0, self.model.columnCount()):
            if i == 2:
                self.view.setColumnHidden(i, True)

        # Adjust column widths
        self.view.setColumnWidth(0, 160)  # Name
        self.view.setColumnWidth(1, 80)   # Size
        self.view.setColumnWidth(3, 160)  # Date
        self.view.setColumnWidth(4, 80)   # Profile Length
        self.view.setColumnWidth(5, 10)   # Checkbox

        # Move the checkbox column to first position
        header_view = self.view.header()
        header_view.moveSection(5, 0)

        layout.addWidget(self.view)

        self.model.dataChanged.connect(self.on_files_updated)

    def set_directory(self, path):
        # Validate that the path exists and is a directory
        if not os.path.exists(path) or not os.path.isdir(path):
            print(f"Invalid directory path provided to FileView: '{path}'")
            return

        self.model.setRootPath(path)
        root_index = self.proxy_model.mapFromSource(self.model.index(path))
        if not root_index.isValid():
            print("Invalid index encountered in FileView!")
            print(f"\tIndex: {root_index}")
            print(f"\tPath: '{path}'")
            return
        self.view.setRootIndex(root_index)

    def on_file_selected(self, selected, deselected):
        indexes = selected.indexes()
        if len(indexes):
            selected = indexes[0]
            source_index = self.proxy_model.mapToSource(selected)
            file_path = self.model.filePath(source_index)
            self.file_selected.emit(file_path)

    def on_files_updated(self, **args):
        self.profile_state_changed.emit()

    def on_selection_cleared(self):
        self.file_selected.emit('')

