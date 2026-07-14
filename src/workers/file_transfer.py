"""
This module contains the worker and manager for file transfers.
"""
import logging
import os
import threading
from pathlib import Path

from models.FileTransfer import FileTransferModel, FileTransferItem
from PySide6.QtCore import QObject, Signal, QThread
from gui.widgets.messagebox import show_error_msgbox
from rqft.client import ProgressPhase, SyncCancelled, SyncClient, SyncProgress
from rqft.serial_transport import SerialTransport

log = logging.getLogger(__name__)


class FileTransferWorker(QObject):
    """
    Worker for downloading device files using the RQFT protocol.

    Files already present locally with matching size and CRC32 are skipped;
    the rest are fetched, verified, and committed atomically.

    Signals:
        receivingFile(str, int): Emitted when a file has been received.
                                 (filename, files_left)
        fileByteProgress(int, int): Emitted during the transfer batch.
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
        self._cancel_event = threading.Event()
        self._running = True

    def run(self):
        """
        Starts the file transfer process.
        """
        log.info(f"Starting RQFT sync to {self.folder_path} on port {self.port_name}")
        try:
            transport = SerialTransport(self.port_name, baudrate=115200)
        except Exception as e:
            log.error(f"Failed to open serial port {self.port_name}: {e}")
            self.error.emit(str(e))
            self.finished.emit()
            return

        client = SyncClient(
            transport,
            Path(self.folder_path),
            progress=self._on_progress,
            cancel_event=self._cancel_event,
        )
        try:
            result = client.sync_from_peer(delete_remote=False)
            log.info(
                f"RQFT sync finished: fetched={len(result.fetched)} "
                f"skipped={len(result.skipped)} deleted={len(result.deleted)}"
            )
        except SyncCancelled:
            log.info("RQFT sync cancelled by user")
        except Exception as e:
            log.error(f"Error during RQFT sync: {e}")
            if self._running:
                self.error.emit(str(e))
        finally:
            try:
                client.close()
            except Exception as e:
                log.error(f"Error while closing transport: {e}")
            self.stop()
            self.finished.emit()
            log.info("File transfer finished.")

    def _on_progress(self, progress: SyncProgress):
        """
        Maps RQFT progress events to the transfer signals. Runs in the
        worker thread; Qt delivers the signals across threads.
        """
        if not self._running:
            return
        if progress.phase is ProgressPhase.GET and progress.path:
            # files_left includes the file just reported, matching the
            # countdown semantics the dialog expects.
            files_left = progress.files_total - progress.files_done + 1
            self.receivingFile.emit(progress.path, files_left)
        self.fileByteProgress.emit(progress.bytes_done, progress.bytes_total)

    def stop(self):
        """
        Requests cancellation of the transfer. Idempotent and non-blocking:
        the client sends ABORT(E_USER) and closes the port from the worker
        thread.
        """
        if not self._running:
            return
        log.info("Stopping file transfer worker.")
        self._running = False
        self._cancel_event.set()


class FileTransferManager(QObject):
    """
    Manages the file transfer process using a worker thread.
    """
    transferStarted = Signal()
    transferFinished = Signal(list)
    fileByteProgress = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread: QThread = None
        self.worker: FileTransferWorker = None
        self.model: FileTransferModel = FileTransferModel()
        self.sync_folder_path = None
        self._on_complete_callback = None
        self._transfer_in_progress = False
        self.synced_folders = []

    def is_transfer_in_progress(self):
        return self._transfer_in_progress

    def start_transfer(self, port, folder_path, on_complete):
        """
        Starts a new file transfer.
        """
        if self._transfer_in_progress:
            log.warning("File transfer already in progress.")
            return

        self._transfer_in_progress = True
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
        if self._transfer_in_progress and self.worker:
            log.info("Requesting to cancel file transfer.")
            self.worker.stop()

    def _cleanup(self):
        """
        Called when the thread has finished executing. Cleans up references.
        """
        log.debug("Cleaning up thread and worker references.")
        self.thread = None
        self.worker = None
        self._transfer_in_progress = False
        self.transferFinished.emit(self.synced_folders)
        self.model.removeItems()

    def on_transfer_error(self, error_message):
        log.error(f"File transfer error received: {error_message}")
        show_error_msgbox(f"Error occurred during file transfer:\n\n{error_message}")

    def on_transfer_finished(self):
        """
        Called when the transfer worker is finished.
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

