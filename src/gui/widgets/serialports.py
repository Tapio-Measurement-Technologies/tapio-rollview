from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel, QMenu, QMessageBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from gui.widgets.EmptyStateView import draw_empty_view_text
from theme import qt as theme_qt
from theme.guidance import set_guidance
from theme.widgets import SectionLabel
from models.SerialPort import SerialPortModel, SerialPortItem, list_ports_common
from workers.file_transfer import FileTransferManager
from workers.device_connection import ConnectionState, DeviceConnectionManager
from workers.port_scanner import PortScanner
from utils.translation import _
from utils import preferences
import store

class SerialPortView(QListView):
    connect_requested = Signal(str)
    disconnect_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._empty_message = _("SERIAL_EMPTY_STATE_NO_DEVICES")

        # Set up the model
        self.model = SerialPortModel()
        self.setModel(self.model)

        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def empty_message(self):
        return self._empty_message

    def paintEvent(self, event):
        super().paintEvent(event)
        draw_empty_view_text(self, self._empty_message)

    def show_context_menu(self, position):
        index = self.indexAt(position)
        if not index.isValid():
            return

        port_item = self.model.getPortItem(index.row())
        if not port_item:
            return

        context_menu = QMenu(self)

        if port_item.is_pinned():
            pin_action = QAction(_("SERIAL_UNPIN_PORT"), self)
            pin_action.triggered.connect(lambda: self.unpin_port(port_item.device))
        else:
            pin_action = QAction(_("SERIAL_PIN_PORT"), self)
            pin_action.triggered.connect(lambda: self.pin_port(port_item.device))

        context_menu.addAction(pin_action)

        if port_item.supports_rqft:
            state = self.model.getConnectionState(port_item.device)
            if state is not None and state is not ConnectionState.DISABLED:
                connect_action = QAction(_("SERIAL_DISCONNECT_DEVICE"), self)
                connect_action.triggered.connect(
                    lambda: self.disconnect_requested.emit(port_item.device))
            else:
                connect_action = QAction(_("SERIAL_CONNECT_DEVICE"), self)
                connect_action.triggered.connect(
                    lambda: self.connect_requested.emit(port_item.device))
            context_menu.addAction(connect_action)

        context_menu.exec_(self.viewport().mapToGlobal(position))

    def pin_port(self, device):
        """Add a port to the pinned ports list"""
        current_pinned = set(preferences.pinned_serial_ports)
        current_pinned.add(device)
        preferences.update_preferences({'pinned_serial_ports': current_pinned})
        self.model.applyFilter()

    def unpin_port(self, device):
        """Remove a port from the pinned ports list"""
        current_pinned = set(preferences.pinned_serial_ports)
        current_pinned.discard(device)
        preferences.update_preferences({'pinned_serial_ports': current_pinned})
        self.model.applyFilter()

    def update_com_ports(self, ports):
        # Clear existing items
        self.model.removeItems()
        # Add valid ports to the model
        for port in ports:
            self.model.addItem(port)

        self.restore_selection()

    def select_item(self, row):
        index = self.model.index(row, 0)  # Assumes a single column
        if index.isValid():
            # Set selection
            self.setCurrentIndex(index)
            # Optionally ensure the item is visible
            self.scrollTo(index)

    def restore_selection(self):
        index = self.model.getSelectedPortIndex()
        self.select_item(index)

class SerialWidget(QWidget):
    device_count_changed = Signal(int)
    scan_started = Signal()
    scan_progress = Signal(int, str)
    scan_finished = Signal()

    def __init__(self, transfer_manager: FileTransferManager,
                 connection_manager: DeviceConnectionManager = None, parent=None):
        super().__init__(parent)

        # Create the COM Ports TreeView
        self.view = SerialPortView()

        self.label = SectionLabel(_("SERIAL_DEVICE_LIST_TITLE"))

        self.scanButton = QPushButton(_("SERIAL_SCAN_BUTTON_TEXT"))
        self.scanButton.clicked.connect(self.scan_devices)
        set_guidance(self.scanButton, _("SERIAL_SCAN_BUTTON_TEXT"),
                    _("GUIDANCE_SCAN_DEVICES"))

        # One primary per view: pulling the measurements off the device is the
        # action this panel exists for. Scanning is how you get there.
        self.syncButton = QPushButton(_("SERIAL_SYNC_BUTTON_TEXT"))
        theme_qt.set_variant(self.syncButton, "primary")
        self.syncButton.clicked.connect(self.sync_data)
        self._set_sync_enabled(False)

        self.transferManager = transfer_manager
        self.connectionManager = connection_manager

        self.scanner = PortScanner(self)

        # Arrange the tree view and button in a vertical layout
        layout = QVBoxLayout(self)
        theme_qt.pad(layout, 2, 2, 2, 2)
        theme_qt.gap(layout, 1)
        layout.addWidget(self.label)
        layout.addWidget(self.view)
        layout.addWidget(self.scanButton)
        layout.addWidget(self.syncButton)

        self.view.selectionModel().currentChanged.connect(self.on_port_selected)
        self.scanner.progress.connect(self.scan_progress)
        self.scanner.finished.connect(self.on_scan_finished)
        self.transferManager.transferStarted.connect(self._on_transfer_started)
        self.transferManager.transferFinished.connect(self._on_transfer_finished)

        if self.connectionManager is not None:
            self.view.model.connection_state_provider = self.connectionManager.connection_state
            self.view.connect_requested.connect(self.connectionManager.manual_connect)
            self.view.disconnect_requested.connect(self.connectionManager.manual_disconnect)
            self.connectionManager.connectionStateChanged.connect(self.view.model.refreshStates)

    def _set_sync_enabled(self, enabled):
        """Enable or disable Sync, and say in the tooltip why it is off.

        A greyed-out primary button that gives no reason is where an operator
        gets stuck. Qt still shows a tooltip on a disabled widget, so the answer
        is one hover away instead of a phone call.

        The reason is read back off the state that was just set rather than
        asked of the transfer manager again: what the button is doing and what
        it says about itself then cannot come apart.
        """
        self.syncButton.setEnabled(enabled)
        if enabled:
            detail = _("GUIDANCE_SYNC_DEVICE")
        elif self.view.selectionModel().hasSelection():
            detail = _("GUIDANCE_SYNC_BUSY")
        else:
            detail = _("GUIDANCE_SYNC_NEEDS_DEVICE")
        set_guidance(self.syncButton, _("SERIAL_SYNC_BUTTON_TEXT"), detail)

    def on_port_selected(self, current, previous):
        if not current.isValid():
            self._set_sync_enabled(False)
            self.view.model.selectPort(None)
            return

        selected_port_device = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectPort(selected_port_device)
        self._set_sync_enabled(current.isValid() and not self.transferManager.is_transfer_in_progress())

    def stop_scan(self):
        """Stop a scan in progress. Non-blocking; the worker winds down."""
        self.scanner.request_stop()

    def scan_devices(self):
        self.scanButton.setDisabled(True)
        self.scan_started.emit()
        self.view.model.removeItems()

        # Add pinned ports first, so they are visible during scan
        for device in preferences.pinned_serial_ports:
            port_info = list_ports_common.ListPortInfo(device)
            port_info.description = ""
            port_info.serial_number = ""
            self.view.model.addItem(SerialPortItem(port_info))
        self.view.model.applyFilter()

        busy_ports = (
            self.connectionManager.busy_ports()
            if self.connectionManager is not None
            else None
        )
        self.scanner.start(busy_ports=busy_ports)

    def on_scan_finished(self, ports):
        for port in ports:
            self.view.model.upsertItem(port)

        valid_devices = [p for p in self.view.model.ports if p.device_responded]
        self.device_count_changed.emit(len(valid_devices))
        self.scanButton.setDisabled(False)
        self.view.model.applyFilter()
        if self.connectionManager is not None:
            # Open persistent connections to RQFT-capable devices
            self.connectionManager.on_scan_results(self.view.model.ports)
        self.scan_finished.emit()

    def sync_data(self):
        sync_folder = store.root_directory
        port_item = self.view.model.getSelectedPort()
        if not port_item:
            return
        # No completion callback: a sync reports itself through the window's
        # status bar now, and there is no dialog left to close.
        self.transferManager.start_transfer(
            port_item.device,
            sync_folder,
            None,
            supports_rqft=port_item.supports_rqft,
        )

    def _on_transfer_started(self):
        self._set_sync_enabled(False)

    def _on_transfer_finished(self, *_):
        # Re-enable sync button only if a valid port is still selected
        if self.view.selectionModel().hasSelection():
            self._set_sync_enabled(True)
