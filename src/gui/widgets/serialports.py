from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel, QMenu
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from models.SerialPort import SerialPortModel, SerialPortItem
from gui.filetransferdialog import FileTransferDialog
from gui.widgets.ProgressBarDialog import ProgressBarDialog
from workers.file_transfer import FileTransferManager
from workers.port_scanner import PortScanner
from utils.translation import _
from utils import preferences
import store

class SerialPortView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the model
        self.model = SerialPortModel()
        self.setModel(self.model)

        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

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
        context_menu.exec_(self.viewport().mapToGlobal(position))

    def pin_port(self, device):
        """Add a port to the pinned ports list"""
        current_pinned = set(preferences.pinned_serial_ports)
        current_pinned.add(device)
        preferences.update_pinned_serial_ports(list(current_pinned))
        self.model.applyFilter()

    def unpin_port(self, device):
        """Remove a port from the pinned ports list"""
        current_pinned = set(preferences.pinned_serial_ports)
        current_pinned.discard(device)
        preferences.update_pinned_serial_ports(list(current_pinned))
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

    def __init__(self, transfer_manager: FileTransferManager, parent=None):
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
        self.transferDialog = FileTransferDialog(self.transferManager)

        self.scanner = PortScanner(self)
        self.scan_progress_dialog = None

        # Arrange the tree view and button in a vertical layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.view)
        layout.addWidget(self.scanButton)
        layout.addWidget(self.syncButton)

        self.view.selectionModel().currentChanged.connect(self.on_port_selected)
        self.scanner.finished.connect(self.on_scan_finished)
        self.transferManager.transferStarted.connect(self._on_transfer_started)
        self.transferManager.transferFinished.connect(self._on_transfer_finished)

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

        self.scan_progress_dialog = ProgressBarDialog(auto_close=True, parent=self)
        self.scanner.progress.connect(self.scan_progress_dialog.update_progress)
        self.scanner.finished.connect(
            lambda: self.scan_progress_dialog.update_progress(100, _("PORTSCAN_COMPLETE_TEXT"))
        )
        self.scan_progress_dialog.cancelled.connect(self.scanner.stop)

        self.scanner.start()
        self.scan_progress_dialog.show()

    def on_scan_finished(self, ports):
        self.view.update_com_ports(ports)
        valid_devices = [port for port in ports if port.device_responded]
        self.device_count_changed.emit(len(valid_devices))
        self.scanButton.setDisabled(False)
        self.view.model.applyFilter()
        if self.scan_progress_dialog:
            self.scan_progress_dialog.close()

    def sync_data(self):
        sync_folder = store.root_directory
        self.transferDialog.show()
        port_item = self.view.model.getSelectedPort()
        if port_item:
            self.transferManager.start_transfer(port_item.device, sync_folder, self.transferDialog.on_complete)

    def _on_transfer_started(self):
        self.syncButton.setEnabled(False)

    def _on_transfer_finished(self, *_):
        # Re-enable sync button only if a valid port is still selected
        if self.view.selectionModel().hasSelection():
            self.syncButton.setEnabled(True)
