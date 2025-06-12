from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QProgressBar, QPushButton, QLabel
)
from PySide6.QtCore import Qt, Signal
from utils.translation import _

class ProgressBarDialog(QDialog):
    cancelled = Signal()

    def __init__(self, auto_close=False, parent=None):
        super().__init__(parent)

        self.setWindowTitle(_("PROGRESS_DIALOG_TITLE"))
        self.setFixedSize(300, 150)

        # Store the auto-close option
        self.auto_close = auto_close
        self._is_cancellable = True

        # Create layout and progress bar
        layout = QVBoxLayout(self)

        # Status text label
        self.statusLabel = QLabel(_("PROGRESS_DIALOG_STARTING"), self)
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.statusLabel)

        # Progress bar widget
        self.progressBar = QProgressBar(self)
        self.progressBar.setRange(0, 100)
        self.progressBar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progressBar)

        # Optional: Button to cancel or close the dialog
        self.actionButton = QPushButton(_("BUTTON_TEXT_CANCEL"), self)
        self.actionButton.clicked.connect(self.on_action_button_clicked)
        layout.addWidget(self.actionButton)

    def on_action_button_clicked(self):
        if self._is_cancellable:
            self.cancelled.emit()
            self.actionButton.setEnabled(False)
            self.actionButton.setText(_("BUTTON_TEXT_CANCELLING"))
        else:
            self.close()

    def update_progress(self, value, status_text=""):
        """Updates the progress bar value and the status text."""
        self.progressBar.setValue(value)
        if status_text:
            self.statusLabel.setText(status_text)
        if value >= 100:
            self.actionButton.setText(_("BUTTON_TEXT_CLOSE"))
            self.actionButton.setEnabled(True)  # Enable the button when done
            self._is_cancellable = False
            if self.auto_close:
                self.close()  # Automatically close the dialog if auto_close is enabled

    def reset(self):
        """Resets the progress bar and the button."""
        self.progressBar.setValue(0)
        self.statusLabel.setText(_("PROGRESS_DIALOG_STARTING"))
        self.actionButton.setText(_("BUTTON_TEXT_CANCEL"))
        self.actionButton.setEnabled(True)
        self._is_cancellable = True