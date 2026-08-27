from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QMessageBox
)
import settings
from theme import qt as theme_qt
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
        theme_qt.pad(layout, 4)
        theme_qt.gap(layout, 2)

        # Error message
        error_label = QLabel(
            f"<h3>{_('CRASH_DIALOG_HEADING')}</h3>"
            + _("CRASH_DIALOG_MESSAGE").format(email=settings.CRASH_DIALOG_CONTACT_EMAIL)
        )
        error_label.setWordWrap(True)
        error_label.setOpenExternalLinks(True)
        layout.addWidget(error_label)

        # Traceback display. It is code, so it is set in mono.
        self.traceback_edit = QTextEdit()
        self.traceback_edit.setReadOnly(True)
        self.traceback_edit.setFont(theme_qt.mono_font())
        self.traceback_edit.setPlainText(self.traceback_text)

        print(self.traceback_text)

        layout.addWidget(self.traceback_edit)

        # Buttons
        button_layout = QHBoxLayout()

        # Saving the log is the useful thing to do with this dialog, so it is
        # the primary and it comes last, where the eye ends up.
        self.save_button = QPushButton(_("SAVE_ERROR_LOG"))
        theme_qt.set_variant(self.save_button, "primary")
        self.save_button.clicked.connect(self.save_log)

        self.close_button = QPushButton(_("BUTTON_TEXT_CLOSE"))
        self.close_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.save_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def save_log(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"tapio_crash_{timestamp}.log"

        file_path, selected_filter = QFileDialog.getSaveFileName(
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
