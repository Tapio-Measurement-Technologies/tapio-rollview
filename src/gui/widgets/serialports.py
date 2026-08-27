from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel, QMenu, QMessageBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from gui.widgets.EmptyStateView import draw_empty_view_text
from models.SerialPort import SerialPortModel, SerialPortItem, list_ports_common
from gui.filetransferdialog import FileTransferDialog
from gui.widgets.delete_prompt import resolve_delete_after_sync
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
    scan_progress = Signal(int, str)
    scan_finished = Signal()

    def __init__(self, transfer_manager: FileTransferManager,
                 connection_manager: DeviceConnectionManager = None, parent=None):
        super().__init__(parent)

        # Create the COM Ports TreeView
        self.view = SerialPortView()

        self.label = QLabel(_("SERIAL_DEVICE_LIST_TITLE"))

        self.scanButton = QPushButton(_("SERIAL_SCAN_BUTTON_TEXT"))
        self.scanButton.clicked.connect(self.scan_devices)

        self.syncButton = QPushButton(_("SERIAL_SYNC_BUTTON_TEXT"))
        self.syncButton.clicked.connect(self.sync_data)
        self.syncButton.setEnabled(False)

        self.transferManager = transfer_manager
        self.connectionManager = connection_manager
        self.transferDialog = FileTransferDialog(self.transferManager)
        # Full syncs ask here before removing anything from a device.
        self.transferManager.delete_decision_provider = self._ask_delete_after_sync

        self.scanner = PortScanner(self)

        # Arrange the tree view and button in a vertical layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.view)
        layout.addWidget(self.scanButton)
        layout.addWidget(self.syncButton)

        self.view.selectionModel().currentChanged.connect(self.on_port_selected)
        self.scanner.progress.connect(self.scan_progress)
        self.scanner.finished.connect(self.on_scan_finished)
        self.transferManager.transferStarted.connect(self._on_transfer_started)
        self.transferManager.transferFinished.connect(self._on_transfer_finished)
        self.transferManager.syncBatchStarted.connect(self._on_sync_batch_started)

        if self.connectionManager is not None:
            self.view.model.connection_state_provider = self.connectionManager.connection_state
            self.view.connect_requested.connect(self.connectionManager.manual_connect)
            self.view.disconnect_requested.connect(self.connectionManager.manual_disconnect)
            self.connectionManager.connectionStateChanged.connect(self.view.model.refreshStates)

    def on_port_selected(self, current, previous):
        if not current.isValid():
            self.syncButton.setEnabled(False)
            self.view.model.selectPort(None)
            return

        selected_port_device = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectPort(selected_port_device)
        self.syncButton.setEnabled(current.isValid() and not self.transferManager.is_transfer_in_progress())

    def scan_devices(self):
        self.scanButton.setDisabled(True)
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
        if not port_item.supports_rqft:
            # ZMODEM has no plan phase; show the dialog right away. RQFT
            # syncs open it from _on_sync_batch_started only when files
            # will actually move, so an up-to-date check stays quiet.
            self._set_dialog_title(port_item.device)
            self.transferDialog.show()
        self.transferManager.start_transfer(
            port_item.device,
            sync_folder,
            self.transferDialog.on_complete,
            supports_rqft=port_item.supports_rqft,
        )

    def _ask_delete_after_sync(self, device_label):
        """Delete-after-sync policy for a full sync: the remembered
        answer, or the first-time question."""
        return resolve_delete_after_sync(device_label, self)

    def _set_dialog_title(self, port):
        title = _("FILE_TRANSFER_DIALOG_TITLE")
        if self.connectionManager is not None:
            title += f" — {self.connectionManager.device_label(port)}"
        self.transferDialog.setWindowTitle(title)

    def _on_sync_batch_started(self, port, nfiles, nbytes):
        # Automatic syncs open the dialog only when files will actually
        # move; empty periodic/doorbell checks stay invisible.
        if nfiles > 0 and not self.transferDialog.isVisible():
            self._set_dialog_title(port)
            self.transferDialog.show()

    def _on_transfer_started(self):
        self.syncButton.setEnabled(False)

    def _on_transfer_finished(self, *_):
        # Close the dialog if it is still open (automatic syncs have no
        # on_complete callback to do it).
        if self.transferDialog.isVisible():
            self.transferDialog.accept()
        # Re-enable sync button only if a valid port is still selected
        if self.view.selectionModel().hasSelection():
            self.syncButton.setEnabled(True)
