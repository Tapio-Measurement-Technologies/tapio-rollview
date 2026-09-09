from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from serial.tools import list_ports_common
import settings
from theme import qt as theme_qt
from theme import tokens as T
from theme.guidance import compose
from utils import preferences
from utils.rqft_support import firmware_supports_rqft
from utils.serial_errors import CAUSE_UNREACHABLE, describe_port_error
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
        reachable=None,
        paired_name="",
        transport="other",
        bluetooth_address=None,
        error_cause=None,
    ):
        self.device = port.device
        self.description = port.description
        self.serial_number = port.serial_number
        self.device_responded = device_responded
        self.firmware_version = getattr(port, "firmware_version", "") or ""
        # None until the port has been probed; then whether it answered.
        self.reachable = reachable
        # The name the operating system pairs the port with, for a
        # Bluetooth unit listed before anything has reached it.
        self.paired_name = paired_name or ""
        self.transport = transport
        self.bluetooth_address = bluetooth_address
        # Why the last probe went unanswered: a utils.serial_errors cause,
        # None when it was answered or nothing has asked yet.
        self.error_cause = error_cause
        # Capability belongs to the firmware, not to whether this port
        # answered the last probe. A unit that has identified itself keeps
        # it through a missed probe: one silent probe used to reclassify a
        # 1.2.0 unit as legacy, and the next sync then went down the ZMODEM
        # path its firmware no longer speaks. A port nothing has identified
        # is still not a device, which is what the first clause holds.
        identified = bool(self.firmware_version) or device_responded or known_device
        self.supports_rqft = identified and firmware_supports_rqft(
            self.firmware_version
        )

    def is_pinned(self):
        return self.device in preferences.pinned_serial_ports

    def label(self):
        """The unit as an operator names it: "Tapio RQP Live (1428495563)",
        or the port when nothing more is known."""
        if not self.description:
            return self.device
        if self.serial_number:
            return f"{self.description} ({self.serial_number})"
        return self.description

    def is_paired_unit(self):
        """A paired Bluetooth unit of ours, known by name before any probe."""
        prefixes = getattr(settings, "SERIAL_PAIRED_DEVICE_NAME_PREFIXES", ())
        return bool(self.paired_name) and any(
            self.paired_name.startswith(prefix) for prefix in prefixes
        )

    def is_listed_without_answer(self):
        """Shown in the list, but nothing has answered on it: a paired unit
        that is off, or a pinned port with nothing behind it."""
        return not self.device_responded and (self.is_paired_unit() or self.is_pinned())


# The ball beside a device answers one question, and the same question for
# every device in the list: can I sync from this right now? Whether it is
# filled says the device is there; the colour says how ready it is. A row
# that is not a device at all — an unrelated port, listed because the
# operator asked to see them all — gets no ball, because the question does
# not apply to it.
BALL_ABSENT = "absent"      # listed and known, but nothing answers
BALL_READY = "ready"        # answers; sync it with the button
BALL_WORKING = "working"    # answers; a persistent connection is coming up
BALL_LIVE = "live"          # answers; connected, and measurements arrive on their own

# One token per state: the fill. Absent is hollow.
_BALL_FILL_ROLE = {
    BALL_ABSENT: None,
    BALL_READY: "accent",
    BALL_WORKING: "warning-mark",
    BALL_LIVE: "good",
}

_ball_icon_cache = {}


def _ball_icon(kind):
    """The ball for one state (built lazily; requires a QGuiApplication,
    so only views should trigger this).

    Colours come from the token table rather than from hex written here,
    and the outline is the fill taken towards the ink, so one token per
    state settles both and the pair stays right in light and in dark.
    """
    t = theme_qt.tokens()
    key = (kind, t.theme)
    icon = _ball_icon_cache.get(key)
    if icon is not None:
        return icon
    role = _BALL_FILL_ROLE.get(kind)
    fill = t.color(role) if role else None
    outline = T.mix(fill, t.color("ink"), 0.62) if fill else t.color("ink-muted")
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
    # The style tints a selected row's decoration towards the highlight, and
    # this ball is not decoration: its colour is the whole of what it says.
    # Selecting a unit is what an operator does just before syncing it, so
    # the tint washed out the one row whose state was being read. Giving the
    # mode a pixmap of its own is what stops the style generating one.
    #
    # Disabled is left to the style. A paired unit that is off is greyed on
    # purpose, ball and all.
    icon.addPixmap(pixmap, QIcon.Mode.Selected)
    _ball_icon_cache[key] = icon
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
    def __init__(self, ports=None, parent=None):
        super().__init__(parent)
        # A fresh list per model: a mutable default here was shared by
        # every model, so ports added to one turned up in the next.
        self.ports = list(ports or [])
        self.filtered_ports = list(self.ports)
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
            return self.guidance_for(item)
        elif role == Qt.ItemDataRole.UserRole:
            return item.device
        elif role == Qt.ItemDataRole.DecorationRole:
            kind = self.ballKind(item)
            return _ball_icon(kind) if kind else None

        return None

    def flags(self, index):
        flags = super().flags(index)
        item = self.getPortItem(index.row()) if index.isValid() else None
        if (
            item is not None
            and item.is_paired_unit()
            and not item.device_responded
            and not item.is_pinned()
        ):
            # A paired unit that is off stays in the list but cannot be the
            # selection: nothing can be synced from a unit that is not
            # there. The style sheet paints a disabled row in the disabled
            # ink, which is the greying; the model cannot colour a row
            # itself, since the row rule's colour wins over any foreground
            # role. Right-click still reaches it, for Connect and pinning.
            return Qt.ItemFlag.NoItemFlags
        return flags

    def ballKind(self, item):
        """Which ball a row shows, or None for a port that is not a device.

        A device that answers can be synced from, whether it speaks RQFT
        or not, so it is filled; only a device that speaks RQFT has a
        connection to be live or coming up.
        """
        if not (item.device_responded or item.is_paired_unit() or item.is_pinned()):
            return None
        if not item.device_responded:
            return BALL_ABSENT
        if not item.supports_rqft:
            return BALL_READY
        state = self.getConnectionState(item.device)
        if state is ConnectionState.CONNECTED:
            return BALL_LIVE
        if state in (
            ConnectionState.CONNECTING,
            ConnectionState.LISTENING,
            ConnectionState.OPEN_BACKOFF,
        ):
            return BALL_WORKING
        # Reachable with no session: nothing is coming by itself, but the
        # sync button works.
        return BALL_READY

    def ball_words(self, item):
        """What the ball beside a row means, in two or three words.

        Short enough for the status row, which is where a row's guidance
        goes. What the state buys the operator is a separate line, and the
        tooltip is where that fits.
        """
        return {
            BALL_READY: _("GUIDANCE_PORT_READY"),
            BALL_WORKING: _("GUIDANCE_PORT_CONNECTING"),
            BALL_LIVE: _("GUIDANCE_PORT_CONNECTED"),
        }.get(self.ballKind(item), "")

    def guidance_for(self, item):
        """The one line the status bar can hold about this row.

        The row is one line high and sits beside whatever the window is
        reporting, so this is the port, the state it is in, and what can be
        done with it: a clause each. What that state means and what to do
        about it is in the tooltip, which has room for a sentence.
        """
        detail = []
        words = self.ball_words(item)
        if words:
            detail.append(words)
        if item.is_listed_without_answer():
            # Named, not explained: "Device not answering", not the sentence
            # that says which device, on which port, and what to try.
            detail.append(
                _("GUIDANCE_PORT_NOT_CHECKED") if item.reachable is None
                else describe_port_error(
                    item.error_cause or CAUSE_UNREACHABLE, item.device, item.label()
                ).title
            )
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
        if self.selected_port is not None and self.selected_port.device == new_item.device:
            # The selection follows the port, not the object: a sync reads
            # what the port last reported, not what it said when clicked.
            self.selected_port = new_item
        for i, item in enumerate(self.ports):
            if item.device == new_item.device:
                self.ports[i] = new_item
                self.applyFilter()
                return
        # If the item was not found, add it
        self.addItem(new_item)
        self.applyFilter()

    def findItem(self, device):
        for item in self.ports:
            if item.device == device:
                return item
        return None

    def removeItem(self, row):
        actual_index = self.ports.index(self.filtered_ports[row])  # Get actual index in main list
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.ports[actual_index]
        self.endRemoveRows()
        self.applyFilter()  # Reapply filter after removing item

    def removeDevice(self, device):
        """Drop a port that is no longer there, shown or not. A selection
        on it is cleared, so nothing can sync to a port that has gone."""
        remaining = [item for item in self.ports if item.device != device]
        if len(remaining) == len(self.ports):
            return
        if self.selected_port is not None and self.selected_port.device == device:
            self.selected_port = None
        self.beginResetModel()
        self.ports = remaining
        self.endResetModel()
        self.applyFilter()

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
            # Pinned ports always, then the units that answered. A paired
            # unit that is not answering is not listed: an old pairing for a
            # unit nobody is going to switch on is a row that can never do
            # anything, and there is usually more than one of them. Pin it
            # to keep it in view, or turn on every COM port below.
            pinned_ports = [item for item in self.ports if item.is_pinned()]
            responded_ports = [item for item in self.ports if item.device_responded and not item.is_pinned()]
            # Sort each list by serial port name
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
