from PySide6.QtWidgets import QFileSystemModel, QWidget, QVBoxLayout
from PySide6.QtCore import QDir, Qt, QSortFilterProxyModel, Signal, QModelIndex
from gui.widgets.ContextMenuTreeView import ContextMenuTreeView
import settings

class CustomFilterProxyModel(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row, source_parent):
        index = self.sourceModel().index(source_row, 0, source_parent)
        file_name = self.sourceModel().fileName(index)
        if file_name == "mean.prof":
            return False
        return super().filterAcceptsRow(source_row, source_parent)


class CustomFileSystemModel(QFileSystemModel):
    def columnCount(self, parent=QModelIndex()):
        return super().columnCount(parent) + 1  # Adding one custom column

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        if index.column() == 3:  # Original timestamp column
            if role == Qt.ItemDataRole.DisplayRole:
                if settings.CUSTOM_DATE_FORMAT:
                    file_info = self.fileInfo(index)
                    timestamp = file_info.lastModified()
                    # Convert QDateTime to Python's datetime
                    py_datetime = timestamp.toPython()
                    # Format using Python's strftime
                    formatted_timestamp = py_datetime.strftime(settings.CUSTOM_DATE_FORMAT)
                    return formatted_timestamp
                else:
                    return super().data(index, role)

        if index.column() == 4:  # Custom column index (starting from 0)
            if role == Qt.ItemDataRole.DisplayRole:
                file_info = self.fileInfo(index)
                size = file_info.size()
                prof_len = (size / 8) * (1 / settings.SAMPLE_INTERVAL)
                return f"{prof_len:.2f} m"
        return super().data(index, role)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 4:  # Custom column index
                return "Profile length"
        return super().headerData(section, orientation, role)

class FileTreeView(ContextMenuTreeView):
    selectionCleared = Signal()

    def __init__(self, model) -> None:
        super().__init__(model)
        self.setMaximumHeight(200)
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

    def set_directory(self, path):
        self.model().setRootPath(path)
        self.setRootIndex(self.model().index(path))

class FileView(QWidget):
    file_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setMaximumHeight(200)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.model = CustomFileSystemModel()
        self.model.setRootPath(QDir.currentPath())
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.Files)
        self.model.setNameFilters(["*.prof"])  # Set the filter for .prof files
        self.model.setNameFilterDisables(False)  # Enable the name filter

        self.proxy_model = CustomFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self.view = FileTreeView(self.proxy_model)
        self.view.setRootIndex(self.proxy_model.mapFromSource(self.model.index(QDir.currentPath())))
        self.view.selectionModel().selectionChanged.connect(self.on_file_selected)
        self.view.selectionCleared.connect(self.on_selection_cleared)

        # Hide file type column
        for i in range(0, self.model.columnCount()):
            if i in [2]:
                self.view.setColumnHidden(i, True)

        self.view.setColumnWidth(0, 160)
        self.view.setColumnWidth(1, 80)
        self.view.setColumnWidth(3, 160)
        self.view.setColumnWidth(4, 80)

        layout.addWidget(self.view)

    def set_directory(self, path):
        self.model.setRootPath(path)
        self.view.setRootIndex(self.proxy_model.mapFromSource(self.model.index(path)))

    def on_file_selected(self, selected, deselected):
        indexes = selected.indexes()
        if len(indexes):
            selected = indexes[0]
            file_path = self.proxy_model.mapToSource(selected).data()
            self.file_selected.emit(file_path)

    def on_selection_cleared(self):
        self.file_selected.emit('')

