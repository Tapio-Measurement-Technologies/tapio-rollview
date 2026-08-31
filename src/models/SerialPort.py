from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from serial.tools import list_ports_common
from theme.guidance import compose
from utils import preferences
from utils.rqft_support import firmware_supports_rqft
from utils.translation import _
from workers.device_connection import ConnectionState
import re

class SerialPortItem:
    """
    Represents a serial port with its details.
    """
    def __init__(
        self,
        port: list_ports_common.ListPortInfo,
        device_responded=False,
        known_device=False,
    ):
        self.device = port.device
        self.description = port.description
        self.serial_number = port.serial_number
        self.device_responded = device_responded
        self.firmware_version = getattr(port, "firmware_version", "") or ""
        # A worker-held port may be a known RQFT device without having a
        # live session during this scan.
        self.supports_rqft = (
            device_responded or known_device
        ) and firmware_supports_rqft(self.firmware_version)

    def is_pinned(self):
        return self.device in preferences.pinned_serial_ports


# Connection indicator colors: (fill, outline); None fill = hollow.
_STATE_BALL_COLORS = {
    ConnectionState.CONNECTED: ("#2eb85c", "#1e7e34"),
    ConnectionState.CONNECTING: ("#f0ad4e", "#c98a1e"),
    ConnectionState.LISTENING: ("#f0ad4e", "#c98a1e"),
    ConnectionState.OPEN_BACKOFF: ("#f0ad4e", "#c98a1e"),
    ConnectionState.DISABLED: (None, "#9a9a9a"),
    None: (None, "#9a9a9a"),
}

_state_icon_cache = {}


def _state_icon(state):
    """Small ball icon for one connection state (built lazily; requires
    a QGuiApplication, so only views should trigger this)."""
    icon = _state_icon_cache.get(state)
    if icon is not None:
        return icon
    fill, outline = _STATE_BALL_COLORS.get(state, _STATE_BALL_COLORS[None])
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(outline))
    if fill is not None:
        painter.setBrush(QColor(fill))
    painter.drawEllipse(1, 1, 9, 9)
    painter.end()
    icon = QIcon(pixmap)
    _state_icon_cache[state] = icon
    return icon

def natural_sort_key(text):
    """
    Convert a string into a list of string and number chunks.
    "COM10" becomes ["COM", 10] which sorts correctly.
    """
    def atoi(text):
        return int(text) if text.isdigit() else text
    return [atoi(c) for c in re.split(r'(\d+)', text)]

class SerialPortModel(QAbstractListModel):
    def __init__(self, ports: list = [], parent=None):
        super().__init__(parent)
        self.ports = ports
        self.filtered_ports = ports
        self.selected_port: SerialPortItem = None
        # Callable(device) -> Optional[ConnectionState]; live state is
        # queried, never stored on items (scans rebuild the items).
        self.connection_state_provider = None

    def rowCount(self, parent=QModelIndex()):
        return len(self.filtered_ports)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.filtered_ports) or index.row() < 0:
            return None

        item = self.filtered_ports[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            pin_icon = "📌" if item.is_pinned() else ""
            display_text = f"{pin_icon} [{item.device}] {item.description}"
            if item.serial_number:
                display_text += f" ({item.serial_number})"
            return display_text
        elif role == Qt.ItemDataRole.StatusTipRole:
            return self.tooltip_for(item)
        elif role == Qt.ItemDataRole.UserRole:
            return item.device
        elif role == Qt.ItemDataRole.DecorationRole:
            if not item.supports_rqft:
                return None
            return _state_icon(self.getConnectionState(item.device))

        return None

    @staticmethod
    def tooltip_for(item):
        """The whole row, which the sidebar is too narrow to show.

        The port name is the identifier, so it is the title; the description
        and the numbers underneath it are what the display line loses first
        when the pane is dragged narrower. The last line is the one nothing
        else says: the pin and the connection live in a context menu, and a
        list gives no sign that it has one.
        """
        detail = [item.description]
        if item.serial_number:
            detail.append(_("GUIDANCE_SERIAL_NUMBER").format(number=item.serial_number))
        if item.firmware_version:
            detail.append(_("GUIDANCE_FIRMWARE_VERSION").format(version=item.firmware_version))
        if item.is_pinned():
            detail.append(_("GUIDANCE_PORT_PINNED"))
        action = (_("GUIDANCE_PORT_ACTIONS_RQFT") if item.supports_rqft
                  else _("GUIDANCE_PORT_ACTIONS"))
        return compose(item.device, detail, action)

    def getConnectionState(self, device):
        if self.connection_state_provider is None:
            return None
        return self.connection_state_provider(device)

    def refreshStates(self, *args):
        """Repaint connection indicators after a state change."""
        if self.filtered_ports:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.filtered_ports) - 1, 0),
                [Qt.ItemDataRole.DecorationRole],
            )

    def getPortItem(self, row):
        """Get the port item at the specified row"""
        if 0 <= row < len(self.filtered_ports):
            return self.filtered_ports[row]
        return None

    def addItem(self, item):
        self.ports.append(item)

    def upsertItem(self, new_item):
        """Update an item if it exists, otherwise add it."""
        for i, item in enumerate(self.ports):
            if item.device == new_item.device:
                self.ports[i] = new_item
                self.applyFilter()
                return
        # If the item was not found, add it
        self.addItem(new_item)
        self.applyFilter()

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
            # Filter to only show ports with device_responded = True, but always include pinned ports
            pinned_ports = [item for item in self.ports if item.is_pinned()]
            responded_ports = [item for item in self.ports if item.device_responded and not item.is_pinned()]
            # Sort both lists by serial port name
            pinned_ports.sort(key=lambda x: natural_sort_key(x.device))
            responded_ports.sort(key=lambda x: natural_sort_key(x.device))
            self.filtered_ports = pinned_ports + responded_ports
        else:
            # Show all ports, but pinned ports first
            pinned_ports = [item for item in self.ports if item.is_pinned()]
            other_ports = [item for item in self.ports if not item.is_pinned()]
            # Sort both lists by serial port name
            pinned_ports.sort(key=lambda x: natural_sort_key(x.device))
            other_ports.sort(key=lambda x: natural_sort_key(x.device))
            self.filtered_ports = pinned_ports + other_ports

        self.layoutChanged.emit()  # Notify the view that the data has changed
