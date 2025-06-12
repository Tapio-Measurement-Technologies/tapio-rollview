from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from serial.tools import list_ports_common
from utils import preferences

class SerialPortItem:
    """
    Represents a serial port with its details.
    """
    def __init__(self, port: list_ports_common.ListPortInfo, device_responded=False):
        self.device = port.device
        self.description = port.description
        self.serial_number = port.serial_number
        self.device_responded = device_responded

class SerialPortModel(QAbstractListModel):
    def __init__(self, ports: list = [], parent=None):
        super().__init__(parent)
        self.ports = ports
        self.filtered_ports = ports
        self.selected_port: SerialPortItem = None

    def rowCount(self, parent=QModelIndex()):
        return len(self.filtered_ports)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.filtered_ports) or index.row() < 0:
            return None

        item = self.filtered_ports[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"[{item.device}] {item.description} ({item.serial_number})"
        elif role == Qt.ItemDataRole.UserRole:
            return item.device

        return None

    def addItem(self, item):
        self.ports.append(item)
        self.applyFilter()  # Reapply the filter after adding a new item

    def removeItem(self, row):
        actual_index = self.ports.index(self.filtered_ports[row])  # Get actual index in main list
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.ports[actual_index]
        self.endRemoveRows()
        self.applyFilter()  # Reapply filter after removing item

    def removeItems(self):
        self.beginRemoveRows(QModelIndex(), 0, self.rowCount())
        self.ports = []
        self.endRemoveRows()
        self.applyFilter()

    def selectPort(self, selected):
        if not selected:
            return None
        for index, port in enumerate(self.filtered_ports):
            if port.device == selected:
                self.selected_port = port
                return index
        return None

    def getSelectedPort(self):
        return self.selected_port

    def getSelectedPortIndex(self):
        if not self.selected_port:
            return -1
        for index, port in enumerate(self.filtered_ports):
            if port.device == self.selected_port.device:
                return index
        return -1

    def applyFilter(self):
        """ Apply the filter and update the filtered_ports list. """
        if not preferences.show_all_com_ports:
            # Filter to only show ports with device_responded = True
            self.filtered_ports = [item for item in self.ports if item.device_responded]
        else:
            # Show all ports
            self.filtered_ports = self.ports

        self.layoutChanged.emit()  # Notify the view that the data has changed
