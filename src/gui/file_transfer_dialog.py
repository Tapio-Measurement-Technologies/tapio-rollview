"""What a sync is doing, in a window of its own.

A sync has more to say than a status bar line can hold: which file of how
many is arriving, what it is called, how far through it is, and how far
through the batch that leaves us. Put on one line those numbers change
length as they change value, so the row jumps about and the tail of it is
the first thing to be cut off.

So the sync reports here, and the status bar keeps what it is good at:
the one-line summary once the sync is over, and the postprocessors that
follow it.

The dialog is a passive view. The window drives every update, so a change
of wording or ordering happens in one place rather than being raced
between two objects listening to the same signals.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from theme import qt as theme_qt
from utils.file_utils import format_bytes
from utils.translation import _


class FileTransferDialog(QDialog):
    """The progress of one sync, from the first question to the last file."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._total_files = 0
        self._file_number = 0
        self._cancelling = False

        self.setWindowTitle(_("FILE_TRANSFER_DIALOG_TITLE"))
        self.setMinimumWidth(420)
        # A sync is not a question the window is asking, so it does not take
        # the application over; the operator can keep reading a measurement
        # while it runs.
        self.setModal(False)

        layout = QVBoxLayout(self)
        theme_qt.pad(layout, 3)
        theme_qt.gap(layout, 2)

        self.status_label = QLabel(_("SYNC_CHECKING_TEXT"))
        theme_qt.set_role(self.status_label, "title")
        layout.addWidget(self.status_label)

        # How much the device said it is about to send. Stated once, up
        # front: it is what tells the operator whether to wait or walk away.
        self.batch_label = QLabel("")
        theme_qt.set_role(self.batch_label, "hint")
        layout.addWidget(self.batch_label)

        # The file in flight. Not a group box: an untitled one is a box drawn
        # around nothing, and the file name is already the label.
        self.current_file_label = QLabel("")
        theme_qt.set_property(self.current_file_label, "role", "data")
        self.current_file_progress_bar = QProgressBar(self)
        self.current_file_progress_bar.setTextVisible(False)
        self.current_file_byte_label = QLabel("")
        theme_qt.set_role(self.current_file_byte_label, "hint")
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.current_file_progress_bar)
        layout.addWidget(self.current_file_byte_label)

        total_group = QGroupBox(_("FILE_TRANSFER_DIALOG_TOTAL"))
        total_layout = QVBoxLayout(total_group)
        theme_qt.pad(total_layout, 3, 2, 3, 3)
        theme_qt.gap(total_layout, 2)
        self.total_progress_bar = QProgressBar(self)
        self.total_progress_bar.setTextVisible(False)
        total_layout.addWidget(self.total_progress_bar)
        layout.addWidget(total_group)

        # Cancelling stops work in progress; what has arrived is kept, so it
        # destroys nothing and is not the danger variant.
        self.cancel_button = QPushButton(_("BUTTON_TEXT_CANCEL"), self)
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_button)

    # -- what the window drives -----------------------------------------

    def begin(self, unit_label=""):
        """A sync has started. Nothing can be counted until the device says
        how many files it holds, and a device that is switched off answers
        exactly as fast as one that is thinking: that wait is what the
        indeterminate bar is for."""
        self._total_files = 0
        self._file_number = 0
        self._cancelling = False
        title = _("FILE_TRANSFER_DIALOG_TITLE")
        if unit_label:
            title = f"{title} — {unit_label}"
        self.setWindowTitle(title)
        self.status_label.setText(_("SYNC_CHECKING_TEXT"))
        self.batch_label.setText("")
        self.current_file_label.setText("")
        self.current_file_byte_label.setText("")
        self.current_file_progress_bar.setValue(0)
        # No file is arriving yet, and an empty bar under a blank name is a
        # measurement of nothing. They appear when the first file does.
        self._show_current_file(False)
        self.total_progress_bar.setRange(0, 0)
        self.cancel_button.setText(_("BUTTON_TEXT_CANCEL"))
        self.cancel_button.setEnabled(True)
        if not self.isVisible():
            self.show()
        self.raise_()

    def set_batch(self, file_count, byte_count):
        """The device has said what it is about to send."""
        if file_count <= 0:
            return
        self._total_files = file_count
        self.batch_label.setText(
            _("SYNC_BATCH_STATUS").format(
                count=file_count, size=format_bytes(byte_count))
        )
        self.total_progress_bar.setRange(0, 100)
        self.total_progress_bar.setValue(0)

    def set_current_file(self, number, total, filename):
        """A file started arriving."""
        self._file_number = number
        self._total_files = total or self._total_files
        self.status_label.setText(
            _("FILE_TRANSFER_DIALOG_RECEIVING").format(
                number=number, total=self._total_files)
        )
        self.current_file_label.setText(filename)
        self.current_file_progress_bar.setValue(0)
        self.current_file_byte_label.setText("")
        self._show_current_file(True)
        self._show_total(0.0)

    def set_byte_progress(self, transferred, total_bytes):
        """The file in flight moved."""
        fraction = (transferred / total_bytes) if total_bytes else 0.0
        self.current_file_progress_bar.setValue(int(fraction * 100))
        self.current_file_byte_label.setText(
            f"{format_bytes(transferred)} / {format_bytes(total_bytes)}"
            if total_bytes else ""
        )
        self._show_total(fraction)

    def finish(self):
        """The sync is over, however it ended."""
        self._cancelling = False
        if self.isVisible():
            self.hide()

    def cancel(self):
        """Stop the sync. The files already written stay written, so this
        loses nothing that has arrived.

        The dialog stays up until the transfer actually ends: a Bluetooth
        read can be seconds from returning, and a window that vanished on
        the press would claim the sync had stopped before it had.
        """
        if self._cancelling:
            return
        self._cancelling = True
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText(_("BUTTON_TEXT_CANCELLING"))
        self.manager.cancel_transfer()

    # -- Qt --------------------------------------------------------------

    def reject(self):
        """Escape, or the window's close button.

        This window is the only place a running sync can be seen or
        stopped, so dismissing it means stopping the sync rather than
        leaving it running where nothing reports it.
        """
        self.cancel()

    def _show_current_file(self, visible):
        for widget in (
            self.current_file_label,
            self.current_file_progress_bar,
            self.current_file_byte_label,
        ):
            widget.setVisible(visible)

    def _show_total(self, fraction_of_current):
        """Whole-transfer percent, counting the file in flight as a
        fraction of itself. A bar that only moved between files would sit
        still for the whole of a single large profile."""
        if self._total_files <= 0:
            return
        completed = self._file_number - 1 + fraction_of_current
        percent = int((completed / self._total_files) * 100)
        if self.total_progress_bar.maximum() == 0:
            self.total_progress_bar.setRange(0, 100)
        self.total_progress_bar.setValue(max(0, min(100, percent)))
