from PySide6.QtWidgets import QDialog, QProgressBar, QPushButton, QVBoxLayout, QApplication, QLabel, QGroupBox
from PySide6.QtCore import QModelIndex
from workers.file_transfer import FileTransferManager
from utils.translation import _

class FileTransferDialog(QDialog):
    def __init__(self, manager: FileTransferManager):
        super().__init__()
        self.setWindowTitle(_("FILE_TRANSFER_DIALOG_TITLE"))
        self.setMinimumWidth(400)
        self.layout = QVBoxLayout(self)

        self.manager = manager

        self.status_label = QLabel(_("PROGRESS_DIALOG_STARTING"))
        self.layout.addWidget(self.status_label)

        # Current file progress
        current_file_group = QGroupBox()
        current_file_group.setStyleSheet("QGroupBox { border: none; }")
        current_file_layout = QVBoxLayout(current_file_group)
        current_file_layout.setContentsMargins(0, 5, 0, 5)

        self.current_file_label = QLabel("")
        self.current_file_progress_bar = QProgressBar(self)
        self.current_file_byte_progress_label = QLabel("")
        current_file_layout.addWidget(self.current_file_label)
        current_file_layout.addWidget(self.current_file_progress_bar)
        current_file_layout.addWidget(self.current_file_byte_progress_label)
        self.layout.addWidget(current_file_group)

        # Total progress
        total_progress_group = QGroupBox(_("TOTAL_PROGRESS"))
        total_progress_layout = QVBoxLayout(total_progress_group)
        total_progress_layout.setContentsMargins(5, 5, 5, 5)
        self.total_progress_bar = QProgressBar(self)
        total_progress_layout.addWidget(self.total_progress_bar)
        self.layout.addWidget(total_progress_group)

        self.layout.addStretch(1)

        self.cancel_button = QPushButton(_("BUTTON_TEXT_CANCEL"), self)
        self.cancel_button.clicked.connect(self.on_cancel)
        self.layout.addWidget(self.cancel_button)

        self.manager.model.rowsInserted.connect(self.update_progress)
        self.manager.fileByteProgress.connect(self.update_byte_progress)
        self.adjustSize()

    def on_cancel(self):
        print("File transfer cancelled")
        self.manager.cancel_transfer()
        self.reject()  # Closes the dialog and returns QDialog.Rejected

    def on_complete(self):
        print("File transfer complete")
        self.accept()

    def update_progress(self, parent=QModelIndex(), first=0, last=0):
        latest = self.manager.model.getLatestItem()
        if not latest:
            return
        total_filecount = self.manager.model.getTotalFileCount()
        file_number = total_filecount - latest.files_remaining + 1

        self.status_label.setText(f"{_('FILE_TRANSFER_DIALOG_RECEIVING')} {file_number} / {total_filecount}...")
        self.current_file_label.setText(latest.filename)
        self.current_file_progress_bar.setValue(0)
        self.current_file_byte_progress_label.setText("")

        if total_filecount > 0:
            total_progress_percent = int(((file_number-1) / total_filecount) * 100)
            self.total_progress_bar.setValue(total_progress_percent)

    def update_byte_progress(self, transferred, total):
        if total > 0:
            progress_percent = int((transferred / total) * 100)
            self.current_file_progress_bar.setValue(progress_percent)
            self.current_file_byte_progress_label.setText(f"{self._format_bytes(transferred)} / {self._format_bytes(total)}")
        else:
            self.current_file_progress_bar.setValue(0)
            self.current_file_byte_progress_label.setText("")

    def _format_bytes(self, size_bytes):
        if size_bytes > 1024*1024:
            return f"{size_bytes / (1024*1024):.2f} MB"
        if size_bytes > 1024:
            return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} bytes"

