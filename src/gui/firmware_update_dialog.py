# Tapio RollView
# Copyright 2026 Tapio Measurement Technologies Oy
#
# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The device firmware update window.

One file, one device, one button. The device has to be on a USB cable:
the update goes through the device's bootloader, which is only reachable
over USB. While an update runs, nothing else in RollView may touch the
device's port, so discovery is paused and the persistent connection on
that port is let go; both come back when the window closes.

A device already sitting in update mode, from an update that was
interrupted, is offered as a target too. That is the recovery path: the
same button, with the restart step skipped.
"""
import logging
import os

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from theme import qt as theme_qt
from theme.guidance import set_guidance
from utils import preferences
from utils.firmware_image import FirmwareImageError, load_device_image
from utils.firmware_update import FirmwareUpdateError, FirmwareUpdater, find_bootloader
from utils.translation import _

log = logging.getLogger(__name__)

#: How often the window looks again for a device to update.
_DEVICE_POLL_MS = 1000

_STATUS_KEYS = {
    "restarting": "FIRMWARE_UPDATE_STATUS_RESTARTING",
    "waiting": "FIRMWARE_UPDATE_STATUS_WAITING",
    "uploading": "FIRMWARE_UPDATE_STATUS_UPLOADING",
    "rebooting": "FIRMWARE_UPDATE_STATUS_REBOOTING",
    "returning": "FIRMWARE_UPDATE_STATUS_RETURNING",
}

_ERROR_KEYS = {
    "port": "FIRMWARE_UPDATE_ERROR_PORT",
    "no_bootloader": "FIRMWARE_UPDATE_ERROR_NO_BOOTLOADER",
    "write": "FIRMWARE_UPDATE_ERROR_WRITE",
    "not_back": "FIRMWARE_UPDATE_ERROR_NOT_BACK",
}


class _UpdateWorker(QObject):
    """Runs one FirmwareUpdater on its own thread and reports by signal."""

    status = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str)       # the port the device came back on
    failed = Signal(str, str)    # kind, detail

    def __init__(self, image, port):
        super().__init__()
        self._image = image
        self._port = port

    def run(self):
        updater = FirmwareUpdater(status=self.status.emit, progress=self.progress.emit)
        try:
            port = updater.run(self._image, self._port)
        except FirmwareUpdateError as e:
            log.error(f"Firmware update failed ({e.kind}): {e}")
            self.failed.emit(e.kind, str(e))
            return
        except Exception as e:
            log.exception("Firmware update failed")
            self.failed.emit("write", str(e))
            return
        self.finished.emit(port or "")


class FirmwareUpdateDialog(QDialog):
    """``device_provider()`` answers ``(port, label)`` for the unit to
    update over USB, or None. ``hold`` and ``release`` are called around
    the update with that port, so the caller can free it and take it back.
    """

    def __init__(self, device_provider, hold=None, release=None, parent=None):
        super().__init__(parent)
        self._device_provider = device_provider
        self._hold = hold or (lambda port: None)
        self._release = release or (lambda port: None)
        self._image = None
        self._target = None          # (port or None, label)
        self._held_port = None
        self._thread = None
        self._worker = None
        self.running = False
        self.outcome = None          # "ok" | "error" | None

        self.setWindowTitle(_("FIRMWARE_UPDATE_TITLE"))
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        theme_qt.pad(layout, 4)
        theme_qt.gap(layout, 2)

        intro = QLabel(_("FIRMWARE_UPDATE_INTRO"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel(_("FIRMWARE_UPDATE_DEVICE_LABEL")))
        self.device_label = QLabel()
        theme_qt.set_property(self.device_label, "role", "data")
        device_row.addWidget(self.device_label, 1)
        layout.addLayout(device_row)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(_("FIRMWARE_UPDATE_FILE_LABEL")))
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText(_("FIRMWARE_UPDATE_FILE_PLACEHOLDER"))
        theme_qt.set_property(self.file_input, "role", "data")
        file_row.addWidget(self.file_input, 1)
        self.browse_button = QPushButton(_("FIRMWARE_UPDATE_BROWSE"))
        self.browse_button.clicked.connect(self.choose_file)
        file_row.addWidget(self.browse_button)
        layout.addLayout(file_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        theme_qt.set_role(self.status_label, "hint")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = QPushButton(_("BUTTON_TEXT_CLOSE"))
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.upload_button = QPushButton(_("FIRMWARE_UPDATE_UPLOAD"))
        theme_qt.set_variant(self.upload_button, "primary")
        set_guidance(self.upload_button, _("FIRMWARE_UPDATE_UPLOAD"), _("GUIDANCE_FIRMWARE_UPLOAD"))
        self.upload_button.clicked.connect(self.start_update)
        buttons.addWidget(self.upload_button)
        layout.addLayout(buttons)

        self._poll = QTimer(self)
        self._poll.setInterval(_DEVICE_POLL_MS)
        self._poll.timeout.connect(self.refresh_device)
        self._poll.start()
        self.refresh_device()

    # -- the target ---------------------------------------------------------

    def refresh_device(self):
        """Look again for something to update: a unit on USB, or one already
        in update mode."""
        if self.running:
            return
        target = None
        if find_bootloader() is not None:
            target = (None, _("FIRMWARE_UPDATE_DEVICE_IN_UPDATE_MODE"))
        else:
            found = self._device_provider()
            if found is not None:
                target = tuple(found)
        self._target = target
        if target is None:
            self.device_label.setText(_("FIRMWARE_UPDATE_NO_DEVICE"))
        else:
            self.device_label.setText(target[1])
        self._update_buttons()

    def _update_buttons(self):
        ready = self._image is not None and self._target is not None and not self.running
        self.upload_button.setEnabled(ready)
        self.browse_button.setEnabled(not self.running)
        self.close_button.setEnabled(not self.running)

    # -- the file -----------------------------------------------------------

    def choose_file(self):
        start = preferences.__dict__.get("firmware_file_directory") or ""
        path, _filter = QFileDialog.getOpenFileName(
            self, _("FIRMWARE_UPDATE_TITLE"), start, _("FIRMWARE_UPDATE_FILE_FILTER")
        )
        if path:
            self.set_file(path)

    def set_file(self, path):
        """Read and check the file at once: a wrong file is refused before
        anything is pressed, not after the device has been restarted."""
        try:
            self._image = load_device_image(path)
        except FirmwareImageError as e:
            self._image = None
            self.file_input.setText(path)
            self.status_label.setText(f"{_('FIRMWARE_UPDATE_ERROR_BAD_FILE')} ({e})")
            self._update_buttons()
            return False
        self.file_input.setText(path)
        self.status_label.setText(
            _("FIRMWARE_UPDATE_FILE_READY").format(
                name=os.path.basename(path), kb=(self._image.total_size + 1023) // 1024
            )
        )
        self._update_buttons()
        return True

    # -- the update ---------------------------------------------------------

    def start_update(self):
        if self._image is None or self._target is None or self.running:
            return
        port, _label = self._target
        self.running = True
        self.outcome = None
        self._poll.stop()
        self._update_buttons()
        self.progress_bar.setRange(0, 0)     # busy until bytes start moving
        self.status_label.setText(_("FIRMWARE_UPDATE_STATUS_RESTARTING"))
        if port is not None:
            self._held_port = port
            self._hold(port)

        self._thread = QThread(self)
        self._worker = _UpdateWorker(self._image, port)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_status(self, step):
        key = _STATUS_KEYS.get(step)
        if key:
            self.status_label.setText(_(key))
        if step != "uploading":
            self.progress_bar.setRange(0, 0)

    def _on_progress(self, done, total):
        if total <= 0:
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(done * 100 / total))

    def _finish(self):
        self.running = False
        self._release_port()
        self._thread = None
        self._worker = None
        self._poll.start()
        self._update_buttons()

    def _on_finished(self, port):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText(_("FIRMWARE_UPDATE_STATUS_DONE"))
        self.outcome = "ok"
        self._finish()

    def _on_failed(self, kind, detail):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        key = _ERROR_KEYS.get(kind, "FIRMWARE_UPDATE_ERROR_WRITE")
        self.status_label.setText(_(key))
        log.error(f"Firmware update: {detail}")
        self.outcome = "error"
        self._finish()

    def _release_port(self):
        port, self._held_port = self._held_port, None
        if port is not None:
            self._release(port)

    # -- leaving ------------------------------------------------------------

    def closeEvent(self, event):
        if self.running:
            # Not while bytes are moving: an interrupted write leaves the
            # device in update mode, and the window is where that gets fixed.
            event.ignore()
            return
        self._poll.stop()
        self._release_port()
        super().closeEvent(event)

    def reject(self):
        if self.running:
            return
        self._poll.stop()
        self._release_port()
        super().reject()
