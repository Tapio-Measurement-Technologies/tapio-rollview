from PySide6.QtWidgets import QDialog, QProgressBar, QPushButton, QVBoxLayout, QApplication, QLabel
from PySide6.QtCore import QModelIndex
from utils.serial import FileTransferManager
from gettext import gettext as _

class FileTransferDialog(QDialog):
    def __init__(self, manager: FileTransferManager):
        super().__init__()
        self.setWindowTitle(_("FILE_TRANSFER_DIALOG_TITLE"))
        self.layout = QVBoxLayout(self)

        self.manager = manager

        self.progress_label = QLabel(_("PROGRESS_DIALOG_STARTING"))
        self.filename_label = QLabel("")
        self.filecount_label = QLabel("")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximum(100)  # Set to 100 for percentage
        self.cancel_button = QPushButton(_("BUTTON_TEXT_CANCEL"), self)
        self.cancel_button.clicked.connect(self.on_cancel)

        self.layout.addWidget(self.progress_label)
        self.layout.addWidget(self.filename_label)
        self.layout.addWidget(self.filecount_label)
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(self.cancel_button)

        self.manager.model.rowsInserted.connect(self.update_progress)
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
        total_filecount = self.manager.model.getTotalFileCount()
        file_number = total_filecount - latest.files_remaining + 1
        self.filename_label.setText(f"{_("FILE_TRANSFER_DIALOG_RECEIVING")}: {latest.filename}")
        self.filecount_label.setText(f"({file_number} / {total_filecount})")
        progress_percent = int(((file_number-1) / total_filecount) * 100)
        self.progress_bar.setValue(progress_percent)

