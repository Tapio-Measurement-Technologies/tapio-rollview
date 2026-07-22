"""
This module contains the workers and manager for file transfers.

Two transfer paths share one manager (and one signal surface):
- RQFT devices sync through their persistent DeviceConnectionWorker.
- Older devices fall back to the ZMODEM receive worker.
"""
import logging
import os
import serial
import time

from modem import ZMODEM
from models.FileTransfer import FileTransferModel, FileTransferItem
from PySide6.QtCore import QObject, QTimer, Signal, QThread
from gui.widgets.messagebox import show_error_msgbox
from workers.device_connection import describe_sync_error
import store

log = logging.getLogger(__name__)


class ZmodemTransferWorker(QObject):
    """
    Worker for handling file transfer using the ZMODEM protocol, used
    for devices whose firmware predates RQFT.

    Signals:
        receivingFile(str, int): Emitted when a new file starts transferring.
                                 (filename, files_left)
        fileByteProgress(int, int): Emitted during file transfer.
                                   (bytes_transferred, total_bytes)
        finished(): Emitted when the transfer is complete.
        error(str): Emitted on transfer error.
    """
    receivingFile = Signal(str, int)
    fileByteProgress = Signal(int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, port, folder_path):
        super().__init__()
        self.port_name = port
        self.folder_path = folder_path
        self.serial = None
        self._running = True

    def run(self):
        """
        Starts the file transfer process.
        """
        log.info(f"Starting ZMODEM transfer to {self.folder_path} on port {self.port_name}")
        try:
            self.serial = serial.Serial(
                port=self.port_name,
                parity=serial.PARITY_NONE,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5,
                xonxoff=0,
                rtscts=0,
                dsrdtr=0,
                baudrate=115200,
            )
        except serial.SerialException as e:
            log.error(f"Failed to open serial port {self.port_name}: {e}")
            self.error.emit(str(e))
            self.finished.emit()
            return

        def getc(size, timeout=5):
            if not self._running: return None
            try:
                return self.serial.read(size).decode("ISO-8859-1")
            except (serial.SerialException, TypeError):
                # This will happen if port is closed during read
                return None

        def putc(data, timeout=8):
            if not self._running: return None
            try:
                return self.serial.write(data.encode("ISO-8859-1"))
            except (serial.SerialException, TypeError):
                # This will happen if port is closed during write
                return None

        try:
            self.serial.read_all()
            time.sleep(0.1)
            zmodem = ZMODEM(getc, putc, self)
            if self._running:
                zmodem.recv(self.folder_path)
        except Exception as e:
            log.error(f"Error during ZMODEM transfer: {e}")
            if self._running:
                self.error.emit(str(e))
        finally:
            self.stop()
            self.finished.emit()
            log.info("File transfer finished.")

    def stop(self):
        """
        Stops the file transfer and cleans up resources. Idempotent.
        """
        if not self._running:
            return
        log.info("Stopping file transfer worker.")
        self._running = False
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
                log.info("Serial port closed.")
            except (serial.SerialException, TypeError) as e:
                log.error(f"Error while closing serial port: {e}")


# Kept as the patchable name for the ZMODEM QThread path.
FileTransferWorker = ZmodemTransferWorker


class FileTransferManager(QObject):
    """
    Manages file transfers: routes each sync either through the device's
    persistent RQFT connection or through a ZMODEM worker thread, and
    serializes transfers (one at a time across all devices).
    """
    transferStarted = Signal()
    transferFinished = Signal(list)
    fileByteProgress = Signal(int, int)
    # port, nfiles, nbytes — lets the GUI show the dialog for automatic
    # syncs only when there is something to fetch.
    syncBatchStarted = Signal(str, int, int)
    # message, is_auto — errors that should not raise a popup
    transferError = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread: QThread = None
        self.worker: ZmodemTransferWorker = None
        self.model: FileTransferModel = FileTransferModel()
        self.sync_folder_path = None
        self._on_complete_callback = None
        self._transfer_in_progress = False
        self.synced_folders = []
        self._connection_manager = None
        self._active_port = None
        self._active_bridge = None
        self._active_is_auto = False
        self._auto_queue: list[str] = []
        # "ok" | "cancelled" | "error" — how the last transfer ended;
        # lets the GUI report "all up to date" only for clean empty runs.
        self.last_transfer_outcome = "ok"

    def set_connection_manager(self, connection_manager):
        self._connection_manager = connection_manager

    def is_transfer_in_progress(self):
        return self._transfer_in_progress

    def has_pending_sync(self, port):
        """Whether a sync for this port is running or queued."""
        if self._transfer_in_progress and self._active_port == port:
            return True
        return port in self._auto_queue

    # -- entry points --------------------------------------------------

    def start_transfer(self, port, folder_path, on_complete, supports_rqft=False):
        """
        Starts a new (manual) file transfer.
        """
        if self._transfer_in_progress:
            log.warning("File transfer already in progress.")
            return

        conn = None
        if self._connection_manager is not None and supports_rqft:
            # (Re)establish the connection when the user syncs a capable
            # device that is currently disconnected.
            self._connection_manager.manual_connect(port)
            conn = self._connection_manager.get_connection(port)
        if conn is not None:
            self._begin_rqft(port, conn, folder_path, on_complete, auto=False)
        else:
            self._begin_zmodem(port, folder_path, on_complete)

    def request_auto_sync(self, port):
        """
        Queue an automatic sync (doorbell, periodic, on-connect) for a
        connected RQFT device. Deduplicated by port; drained one at a
        time after the running transfer finishes.
        """
        if self._transfer_in_progress or self._auto_queue:
            if port != self._active_port and port not in self._auto_queue:
                self._auto_queue.append(port)
            return
        self._start_auto_sync(port)

    def _start_auto_sync(self, port):
        if self._connection_manager is None:
            return
        conn = self._connection_manager.get_connection(port)
        if conn is None:
            log.info(f"Skipping auto sync for {port}: no active connection")
            return
        self._begin_rqft(port, conn, store.root_directory, None, auto=True)

    def _drain_auto_queue(self):
        if self._transfer_in_progress or not self._auto_queue:
            return
        self._start_auto_sync(self._auto_queue.pop(0))

    # -- RQFT path -----------------------------------------------------

    def _begin_rqft(self, port, conn, folder_path, on_complete, auto):
        bridge = self._connection_manager.bridge_for(port)
        if bridge is None:
            log.error(f"No connection bridge for {port}; cannot sync")
            return

        self._transfer_in_progress = True
        self._active_port = port
        self._active_is_auto = auto
        self.last_transfer_outcome = "ok"
        self.model.removeItems()
        self.synced_folders = []
        self.sync_folder_path = folder_path
        self._on_complete_callback = on_complete
        self._active_bridge = bridge
        bridge.receivingFile.connect(self.update_progress)
        bridge.fileByteProgress.connect(self.fileByteProgress)
        bridge.syncStarted.connect(self._on_sync_started)
        bridge.syncFinished.connect(self._on_rqft_finished)
        bridge.syncFailed.connect(self._on_rqft_failed)

        self.transferStarted.emit()
        log.info(f"Requesting RQFT sync on {port} (auto={auto})")
        conn.request_sync(auto)

    def _release_bridge(self):
        bridge = self._active_bridge
        self._active_bridge = None
        if bridge is None:
            return
        bridge.receivingFile.disconnect(self.update_progress)
        bridge.fileByteProgress.disconnect(self.fileByteProgress)
        bridge.syncStarted.disconnect(self._on_sync_started)
        bridge.syncFinished.disconnect(self._on_rqft_finished)
        bridge.syncFailed.disconnect(self._on_rqft_failed)

    def _on_sync_started(self, port, nfiles, nbytes):
        self.syncBatchStarted.emit(port, nfiles, nbytes)

    def _on_rqft_finished(self, port, fetched, skipped):
        log.info(f"RQFT sync finished on {port}: fetched={len(fetched)} skipped={skipped}")
        self._finish_rqft(fetched)

    def _on_rqft_failed(self, port, error):
        message = describe_sync_error(error)
        is_auto = self._active_is_auto
        self.last_transfer_outcome = (
            "cancelled" if error.kind == "cancelled" else "error"
        )
        if error.kind == "cancelled":
            log.info(f"RQFT sync on {port} cancelled by user")
        else:
            log.error(f"RQFT sync failed on {port} ({error.kind}): {message}")
            self.transferError.emit(message, is_auto)
            if not is_auto and error.kind not in ("busy",):
                show_error_msgbox(f"Error occurred during file transfer:\n\n{message}")
        # Files fetched before the failure are committed and usable.
        self._finish_rqft(error.fetched)

    def _finish_rqft(self, fetched_paths):
        self._release_bridge()
        folder_paths = list({
            os.path.join(self.sync_folder_path, os.path.dirname(path))
            for path in fetched_paths
        })
        if folder_paths:
            log.info(f"Received files in folders: {folder_paths}")
        self.synced_folders = folder_paths

        if self._on_complete_callback:
            self._on_complete_callback()
        self._on_complete_callback = None
        self._transfer_in_progress = False
        self._active_port = None
        self.transferFinished.emit(self.synced_folders)
        self.model.removeItems()
        QTimer.singleShot(0, self._drain_auto_queue)

    # -- ZMODEM path ---------------------------------------------------

    def _begin_zmodem(self, port, folder_path, on_complete):
        self._transfer_in_progress = True
        self._active_port = port
        self._active_is_auto = False
        self.last_transfer_outcome = "ok"
        self.transferStarted.emit()

        self.model.removeItems()
        self.synced_folders = []
        self.sync_folder_path = folder_path
        self._on_complete_callback = on_complete

        self.thread = QThread()
        self.worker = FileTransferWorker(port, folder_path)
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.worker.receivingFile.connect(self.update_progress)
        self.worker.fileByteProgress.connect(self.fileByteProgress)
        self.worker.finished.connect(self.on_transfer_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._cleanup)
        self.worker.error.connect(self.on_transfer_error)

        self.thread.started.connect(self.worker.run)
        log.info("Starting file transfer thread.")
        self.thread.start()

    def cancel_transfer(self):
        """
        Requests cancellation of the ongoing file transfer. This is non-blocking.
        """
        if not self._transfer_in_progress:
            return
        self.last_transfer_outcome = "cancelled"
        if self._active_bridge is not None and self._connection_manager is not None:
            conn = self._connection_manager.get_connection(self._active_port)
            if conn is not None:
                log.info("Requesting to cancel RQFT sync.")
                conn.request_cancel()
            return
        if self.worker:
            log.info("Requesting to cancel file transfer.")
            self.worker.stop()

    def _cleanup(self):
        """
        Called when the ZMODEM thread has finished executing. Cleans up references.
        """
        log.debug("Cleaning up thread and worker references.")
        self.thread = None
        self.worker = None
        self._transfer_in_progress = False
        self._active_port = None
        self.transferFinished.emit(self.synced_folders)
        self.model.removeItems()
        QTimer.singleShot(0, self._drain_auto_queue)

    def on_transfer_error(self, error_message):
        log.error(f"File transfer error received: {error_message}")
        self.last_transfer_outcome = "error"
        show_error_msgbox(f"Error occurred during file transfer:\n\n{error_message}")

    def on_transfer_finished(self):
        """
        Called when the ZMODEM transfer worker is finished.
        """
        if self._on_complete_callback:
            self._on_complete_callback()

        received_files = self.model.getReceivedFiles()
        if received_files:
            folder_paths = list(set([os.path.join(self.sync_folder_path, os.path.dirname(
                received_file)) for received_file in received_files]))
            log.info(f"Received files in folders: {folder_paths}")
            log.info(f"Running postprocessors for: {folder_paths}")
            self.synced_folders = folder_paths

        self.model.removeItems()

    def update_progress(self, filename, filesLeft):
        """
        Adds a new transferred file item to the model.
        """
        self.model.addItem(FileTransferItem(filename, filesLeft))
