from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from serial.tools import list_ports_common

class SerialPortItem:
    def __init__(self, port: list_ports_common.ListPortInfo):
        self.port = port

class SerialPortModel(QAbstractListModel):
    def __init__(self, ports: list = [], parent=None):
        super().__init__(parent)
        self.ports = ports
        self.selected_port: list_ports_common.ListPortInfo = None

    def rowCount(self, parent=QModelIndex()):
        return len(self.ports)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.ports) or index.row() < 0:
            return None

        item = self.ports[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{item.port.description} ({item.port.serial_number})"
        elif role == Qt.ItemDataRole.UserRole:
            return item.port.device

        return None

    def addItem(self, item):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self.ports.append(item)
        self.endInsertRows()

    def removeItem(self, row):
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.ports[row]
        self.endRemoveRows()
    
    def removeItems(self):
        self.beginRemoveRows(QModelIndex(), 0, self.rowCount())
        self.ports = []
        self.endRemoveRows()

    def selectPort(self, selected):
        if not selected:
            return None
        for index, port in enumerate(self.ports):
            if port.port.device == selected:
                self.selected_port = port
                return index
        return None

    def getSelectedPort(self):
        return self.selected_port
    
    def getSelectedPortIndex(self):
        if not self.selected_port:
            return -1
        for index, port in enumerate(self.ports):
            if port.port.device == self.selected_port.port.device:
                return index
        return -1
