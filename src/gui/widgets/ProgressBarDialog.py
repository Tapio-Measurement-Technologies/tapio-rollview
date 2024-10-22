from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QProgressBar, QPushButton, QLabel
)
from PySide6.QtCore import Qt

class ProgressBarDialog(QDialog):
    def __init__(self, auto_close=False, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Progress")
        self.setFixedSize(300, 150)

        # Store the auto-close option
        self.auto_close = auto_close

        # Create layout and progress bar
        layout = QVBoxLayout(self)

        # Status text label
        self.statusLabel = QLabel("Starting...", self)
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.statusLabel)

        # Progress bar widget
        self.progressBar = QProgressBar(self)
        self.progressBar.setRange(0, 100)
        self.progressBar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progressBar)

        # Optional: Button to close the dialog
        self.closeButton = QPushButton("Close", self)
        self.closeButton.setEnabled(False)  # Initially disabled
        self.closeButton.clicked.connect(self.close)
        layout.addWidget(self.closeButton)

    def update_progress(self, value, status_text=""):
        """Updates the progress bar value and the status text."""
        self.progressBar.setValue(value)
        if status_text:
            self.statusLabel.setText(status_text)
        if value >= 100:
            self.closeButton.setEnabled(True)  # Enable the button when done
            if self.auto_close:
                self.close()  # Automatically close the dialog if auto_close is enabled

    def reset(self):
        """Resets the progress bar and the button."""
        self.progressBar.setValue(0)
        self.statusLabel.setText("Starting...")
        self.closeButton.setEnabled(False)