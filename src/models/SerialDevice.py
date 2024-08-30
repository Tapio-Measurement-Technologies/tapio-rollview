from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

class SerialDevice:
    def __init__(self, device):
        self.name = device['name']
        self.port = device['port']
        self.type = device['type']
        if 'host' in device:
            self.host = device['host']

class SerialDeviceModel(QAbstractListModel):
    def __init__(self, devices: list = [], parent=None):
        super().__init__(parent)
        self.devices = devices
        self.selected_device = None

    def rowCount(self, parent=QModelIndex()):
        return len(self.devices)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.devices) or index.row() < 0:
            return None

        item = self.devices[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{item.type} -- {item.name}"
        elif role == Qt.ItemDataRole.UserRole:
            return item

        return None

    def addItem(self, item):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self.devices.append(item)
        self.endInsertRows()
        self.sortItems()  # Sort after adding a new item

    def removeItem(self, row):
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.devices[row]
        self.endRemoveRows()
        self.sortItems()  # Sort after removing an item

    def removeItems(self):
        self.beginRemoveRows(QModelIndex(), 0, self.rowCount() - 1)
        self.devices = []
        self.endRemoveRows()

    def removeItemsByType(self, device_type):
        """
        Remove only devices of a specific type (e.g., 'USB' or 'BT').
        """
        # Identify the indexes of devices to remove
        indexes_to_remove = [i for i, device in enumerate(self.devices) if device.type == device_type]

        # Remove from the end to avoid re-indexing issues
        for index in sorted(indexes_to_remove, reverse=True):
            self.beginRemoveRows(self.index(index), index, index)
            del self.devices[index]
            self.endRemoveRows()

        self.sortItems()  # Sort after removing items of a specific type

    def sortItems(self):
        """
        Sort devices by type and then by name.
        USB devices are listed first, followed by Bluetooth devices.
        """
        self.devices.sort(key=lambda x: (x.type, x.name))
        self.layoutChanged.emit()  # Emit signal to update the view

    def selectDevice(self, selected):
        print(f"selecting device {selected}")
        if not selected:
            return None
        for index, device in enumerate(self.devices):
            if device == selected:
                self.selected_device = device
                return index
        return None

    def getSelectedDevice(self):
        return self.selected_device

    def getSelectedDeviceIndex(self):
        if not self.selected_device:
            return -1
        for index, device in enumerate(self.devices):
            if device == self.selected_device:
                return index
        return -1
