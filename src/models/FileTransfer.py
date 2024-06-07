from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

class FileTransferItem:
    def __init__(self, filename, files_remaining):
        self.filename = filename
        self.files_remaining = files_remaining

class FileTransferModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)
    
    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            self.items[index.row()] = value
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items) or index.row() < 0:
            return None

        item = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        elif role == Qt.ItemDataRole.UserRole:
            return item.files_remaining

        return None

    def getTotalFileCount(self):
        return max(self.items, key=lambda item: item.files_remaining).files_remaining
    
    def getLatestItem(self):
        return self.items[-1]

    def addItem(self, item):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self.items.append(item)
        self.endInsertRows()

    def removeItem(self, row):
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.items[row]
        self.endRemoveRows()

    def removeItems(self):
        self.beginRemoveRows(QModelIndex(), 0, self.rowCount())
        self.items = []
        self.endRemoveRows()
