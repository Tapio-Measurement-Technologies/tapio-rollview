"""
Loading widget with spinner and progress text.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt
from utils.translation import _


class LoadingWidget(QWidget):
    """
    A widget that displays a loading indicator with progress bar and status text.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Loading label
        self.loading_label = QLabel(_("LOADING"), self)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.loading_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.loading_label.setFont(font)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setMaximumWidth(400)

        # Status label
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)

        # Add widgets to layout
        self.layout().addStretch()
        self.layout().addWidget(self.loading_label)
        self.layout().addWidget(self.progress_bar)
        self.layout().addWidget(self.status_label)
        self.layout().addStretch()

    def update_progress(self, value: int, status_text: str = ""):
        """Update the progress bar and status text."""
        self.progress_bar.setValue(value)
        if status_text:
            self.status_label.setText(status_text)

    def reset(self):
        """Reset the progress bar and status text."""
        self.progress_bar.setValue(0)
        self.status_label.setText("")
