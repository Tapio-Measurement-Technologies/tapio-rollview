"""
This module contains the worker and manager for file transfers.
"""
import logging
import os
import serial
import time
from modem import ZMODEM
from models.FileTransfer import FileTransferModel, FileTransferItem
from PySide6.QtCore import QObject, Signal, QThread
from utils.postprocess import run_postprocessors
from gui.widgets.messagebox import show_error_msgbox

log = logging.getLogger(__name__)


class FileTransferWorker(QObject):
    """
    Worker for handling file transfer using ZMODEM protocol.

    Signals:
        receivingFile(str, int): Emitted when a new file starts transferring.
                                 (filename, files_left)
        finished(): Emitted when the transfer is complete.
        error(str): Emitted on transfer error.
    """
    receivingFile = Signal(str, int)
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
        log.info(f"Starting file transfer to {self.folder_path} on port {self.port_name}")
        try:
            self.serial = serial.Serial(
                port=self.port_name,
                parity=serial.PARITY_NONE,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                timeout=5,
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


class FileTransferManager(QObject):
    """
    Manages the file transfer process using a worker thread.
    """
    transferStarted = Signal()
    transferFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread: QThread = None
        self.worker: FileTransferWorker = None
        self.model: FileTransferModel = FileTransferModel()
        self.sync_folder_path = None
        self._on_complete_callback = None
        self._transfer_in_progress = False

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
        self.sync_folder_path = folder_path
        self._on_complete_callback = on_complete

        self.thread = QThread()
        self.worker = FileTransferWorker(port, folder_path)
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.worker.receivingFile.connect(self.update_progress)
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
        self.model.removeItems()

    def _cleanup(self):
        """
        Called when the thread has finished executing. Cleans up references.
        """
        log.debug("Cleaning up thread and worker references.")
        self.thread = None
        self.worker = None
        self._transfer_in_progress = False
        self.transferFinished.emit()

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
            run_postprocessors(folder_paths)

        self.model.removeItems()

    def update_progress(self, filename, filesLeft):
        """
        Adds a new transferred file item to the model.
        """
        self.model.addItem(FileTransferItem(filename, filesLeft))

