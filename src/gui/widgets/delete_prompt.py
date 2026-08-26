"""
The device-side delete policy and its first-run question.

Rollview, not the device, removes measurement files from a device once
they are safely mirrored. Only a full sync deletes; automatic
(incremental) syncs never do. The user decides whether deleting happens
at all: the question is asked before every full sync until "Remember
this choice" stores the answer in preferences, where the Advanced
settings page can change it later.
"""
import logging

from PySide6.QtWidgets import QCheckBox, QMessageBox

import settings
from utils import preferences
from utils.translation import _

log = logging.getLogger(__name__)


def stored_delete_choice():
    """The remembered answer, or None while the user still has to be asked."""
    choice = preferences.delete_synced_files_from_device
    if choice == settings.DELETE_SYNCED_FILES_ALWAYS:
        return True
    if choice == settings.DELETE_SYNCED_FILES_NEVER:
        return False
    return None


def resolve_delete_after_sync(device_label="", parent=None):
    """Whether this full sync may delete synced files from the device.

    Returns the remembered answer when there is one, otherwise asks
    modally and stores the answer when "Remember this choice" is ticked.
    """
    stored = stored_delete_choice()
    if stored is not None:
        return stored
    return _ask(device_label, parent)


def _ask(device_label, parent):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(_("DELETE_AFTER_SYNC_TITLE"))
    box.setText(_("DELETE_AFTER_SYNC_TEXT").format(device=device_label))
    box.setInformativeText(_("DELETE_AFTER_SYNC_INFO"))
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    # Keeping the files is the safe answer, so it is the one a stray
    # Enter or Escape picks.
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setEscapeButton(QMessageBox.StandardButton.No)
    remember_checkbox = QCheckBox(_("DELETE_AFTER_SYNC_REMEMBER"))
    box.setCheckBox(remember_checkbox)

    delete = box.exec() == QMessageBox.StandardButton.Yes
    if remember_checkbox.isChecked():
        remembered = (
            settings.DELETE_SYNCED_FILES_ALWAYS
            if delete
            else settings.DELETE_SYNCED_FILES_NEVER
        )
        preferences.update_preferences(
            {'delete_synced_files_from_device': remembered}
        )
        log.info(f"Remembered delete-after-sync choice: {remembered}")
    return delete
