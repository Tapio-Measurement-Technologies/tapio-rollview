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

        # Connect is offered on a unit that speaks RQFT, and on a paired
        # unit that has not answered, where it means "ask this one next".
        # A unit that answered without RQFT syncs over ZMODEM, which opens
        # the port itself: a connection held on it would only deny that.
        if port_item.supports_rqft or (
            port_item.is_paired_unit() and not port_item.device_responded
        ):
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
    """The device panel: the list, the scan button and the sync button.

    Discovery runs by itself once started: the list fills and empties as
    ports appear, answer, fall silent and go away, one row at a time. The
    scan button is one eager pass over everything, most likely unit first,
    with the status bar showing it; see workers.port_scanner for why that
    is the shape of it.
    """
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
        self._announced_device_count = None
        self._pass_running = False

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
        self.scanner.port_appeared.connect(self.on_port_update)
        self.scanner.port_result.connect(self.on_port_update)
        self.scanner.port_gone.connect(self.on_port_gone)
        self.scanner.finished.connect(self.on_scan_finished)
        self.transferManager.transferStarted.connect(self._on_transfer_started)
        self.transferManager.transferFinished.connect(self._on_transfer_finished)

        if self.connectionManager is not None:
            # The lane reads this from its own thread; it only reads.
            self.scanner.set_busy_ports_provider(self.connectionManager.busy_ports)
            self.view.model.connection_state_provider = self.connectionManager.connection_state
            self.view.connect_requested.connect(self.connect_device)
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
            self.scanner.set_preferred(None)
            return

        selected_port_device = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectPort(selected_port_device)
        # The port the operator is looking at is the one to ask first.
        self.scanner.set_preferred(selected_port_device)
        self._set_sync_enabled(current.isValid() and not self.transferManager.is_transfer_in_progress())

    def stop_scan(self):
        """Stop the pass in progress. Non-blocking; a probe already inside a
        Bluetooth page completes, since nothing can cut one short."""
        self.scanner.request_stop()

    def scan_devices(self):
        """The scan button, and start-up: one eager pass, most likely unit
        first, and every connection in a backoff tries again."""
        self.scanButton.setDisabled(True)
        self._pass_running = True
        self.scan_started.emit()
        if self.connectionManager is not None:
            self.connectionManager.retry_all_now()
        self.scanner.scan_now()

    def on_port_update(self, item):
        """A port appeared or was probed: one row changes, nothing else."""
        self.view.model.upsertItem(item)
        self.view.restore_selection()
        if item.device_responded and self.connectionManager is not None:
            # Open a persistent connection to an RQFT-capable unit as soon
            # as it answers, not at the end of a pass.
            self.connectionManager.on_scan_results([item])
        self._announce_device_count()

    def on_port_gone(self, device):
        """A port is no longer there: unplugged, or the pairing removed."""
        self.view.model.removeDevice(device)
        self.view.restore_selection()
        if not self.view.selectionModel().hasSelection():
            self._set_sync_enabled(False)
        self._announce_device_count()

    def on_scan_finished(self, ports):
        self.scanButton.setDisabled(False)
        self._pass_running = False
        self.view.model.applyFilter()
        self.view.restore_selection()
        self.scan_finished.emit()
        # After scan_finished, not before: the window clears the scan's
        # activity from the status bar on that signal, and the count is
        # what should be left standing there.
        self._announce_device_count(force=True)

    def _announce_device_count(self, force=False):
        """Tell the window how many units answer.

        The count goes to the status bar, so it is announced when a pass
        ends and otherwise only when it changes: every probe result
        repeating "1 device found" would wipe out whatever a sync had just
        said. During a pass the bar is showing the pass itself, so a change
        waits for the end.
        """
        count = len([p for p in self.view.model.ports if p.device_responded])
        if self._pass_running and not force:
            return
        if force or count != self._announced_device_count:
            self._announced_device_count = count
            self.device_count_changed.emit(count)

    def connect_device(self, device):
        """The Connect action: reconnect a unit that has answered, or ask a
        paired unit next and connect when it does."""
        item = self.view.model.findItem(device)
        if item is not None and item.device_responded:
            # Only a unit that speaks RQFT has anything to connect to. One
            # that answered without it must be left alone: a worker on its
            # port would hold the port against the ZMODEM sync.
            if item.supports_rqft and self.connectionManager is not None:
                self.connectionManager.manual_connect(device)
            return
        if self.connectionManager is not None:
            self.connectionManager.allow_auto_connect(device)
        self.scanner.probe_port(device)

    def sync_data(self):
        sync_folder = store.root_directory
        port_item = self.view.model.getSelectedPort()
        if not port_item:
            return
        # The lane sits out the sync from here. Paused first, so no probe of
        # this port can start between the wait and the sync's own open;
        # then waited for, since a probe already inside the port holds it
        # for about a second. If no transfer starts, the lane goes on.
        self.scanner.set_paused(True)
        self.scanner.wait_until_port_free(port_item.device)
        # No completion callback: a sync reports itself through the window's
        # status bar now, and there is no dialog left to close.
        self.transferManager.start_transfer(
            port_item.device,
            sync_folder,
            None,
            supports_rqft=port_item.supports_rqft,
        )
        if not self.transferManager.is_transfer_in_progress():
            self.scanner.set_paused(False)

    def _on_transfer_started(self):
        self._set_sync_enabled(False)
        # Paging an absent unit costs a live link about a third of its
        # throughput; the lane sits out the sync.
        self.scanner.set_paused(True)

    def _on_transfer_finished(self, *_):
        self.scanner.set_paused(False)
        # Re-enable sync button only if a valid port is still selected
        if self.view.selectionModel().hasSelection():
            self._set_sync_enabled(True)
