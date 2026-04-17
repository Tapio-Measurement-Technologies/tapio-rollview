from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QMessageBox
)
import settings
from datetime import datetime
from utils.translation import _

class CrashDialog(QDialog):
    def __init__(self, log_manager, traceback_text, parent=None):
        super().__init__(parent)
        self.log_manager = log_manager
        self.traceback_text = traceback_text
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(_("CRASH_DIALOG_TITLE"))
        self.setMinimumSize(700, 500)

        # Main layout
        layout = QVBoxLayout()

        # Error message
        error_label = QLabel(
            f"<h3>{_('CRASH_DIALOG_HEADING')}</h3>"
            f"<p>{_('CRASH_DIALOG_MESSAGE_LINE_1')}<br>"
            f"{_('CRASH_DIALOG_MESSAGE_LINE_2')} "
            f"<a href='mailto:{settings.CRASH_DIALOG_CONTACT_EMAIL}'>{settings.CRASH_DIALOG_CONTACT_EMAIL}</a>.</p>"
        )
        error_label.setWordWrap(True)
        error_label.setOpenExternalLinks(True)
        layout.addWidget(error_label)

        # Traceback display
        self.traceback_edit = QTextEdit()
        self.traceback_edit.setReadOnly(True)
        self.traceback_edit.setPlainText(self.traceback_text)

        print(self.traceback_text)

        layout.addWidget(self.traceback_edit)

        # Buttons
        button_layout = QHBoxLayout()

        self.save_button = QPushButton(_("SAVE_ERROR_LOG"))
        self.save_button.clicked.connect(self.save_log)

        self.close_button = QPushButton(_("BUTTON_TEXT_CLOSE"))
        self.close_button.clicked.connect(self.reject)

        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.save_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def save_log(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"tapio_crash_{timestamp}.log"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            _("SAVE_CRASH_LOG"),
            default_name,
            _("FILE_DIALOG_LOG_FILTER")
        )

        if file_path:
            (success, msg) = self.log_manager.export_logs(file_path)
            if success:
                QMessageBox.information(self, _("SUCCESS"), msg)
            else:
                QMessageBox.critical(self, _("ERROR"), msg)
