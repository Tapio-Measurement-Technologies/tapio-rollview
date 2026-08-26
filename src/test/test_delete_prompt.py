import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

import settings
from gui.widgets import delete_prompt
from utils import preferences


def _answer_with(button, remember):
    """Stand-in for QMessageBox.exec that ticks the remember box."""

    def answer(box):
        box.checkBox().setChecked(remember)
        return button

    return answer


class TestDeleteAfterSyncPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_choice = preferences.delete_synced_files_from_device
        self.addCleanup(self._restore_choice)
        preferences.delete_synced_files_from_device = settings.DELETE_SYNCED_FILES_ASK

    def _restore_choice(self):
        preferences.delete_synced_files_from_device = self.original_choice

    def test_remembered_yes_deletes_without_asking_again(self):
        preferences.delete_synced_files_from_device = settings.DELETE_SYNCED_FILES_ALWAYS

        with patch.object(delete_prompt, "_ask") as ask:
            self.assertTrue(delete_prompt.resolve_delete_after_sync("RQP Live"))

        ask.assert_not_called()

    def test_remembered_no_keeps_files_without_asking_again(self):
        preferences.delete_synced_files_from_device = settings.DELETE_SYNCED_FILES_NEVER

        with patch.object(delete_prompt, "_ask") as ask:
            self.assertFalse(delete_prompt.resolve_delete_after_sync("RQP Live"))

        ask.assert_not_called()

    def test_remembering_yes_stores_the_always_choice(self):
        with patch.object(
            QMessageBox,
            "exec",
            new=_answer_with(QMessageBox.StandardButton.Yes, remember=True),
        ), patch.object(preferences, "update_preferences") as update:
            self.assertTrue(delete_prompt.resolve_delete_after_sync("RQP Live"))

        update.assert_called_once_with(
            {'delete_synced_files_from_device': settings.DELETE_SYNCED_FILES_ALWAYS}
        )

    def test_remembering_no_stores_the_never_choice(self):
        with patch.object(
            QMessageBox,
            "exec",
            new=_answer_with(QMessageBox.StandardButton.No, remember=True),
        ), patch.object(preferences, "update_preferences") as update:
            self.assertFalse(delete_prompt.resolve_delete_after_sync("RQP Live"))

        update.assert_called_once_with(
            {'delete_synced_files_from_device': settings.DELETE_SYNCED_FILES_NEVER}
        )

    def test_answer_without_remember_is_used_once_and_not_stored(self):
        with patch.object(
            QMessageBox,
            "exec",
            new=_answer_with(QMessageBox.StandardButton.Yes, remember=False),
        ), patch.object(preferences, "update_preferences") as update:
            self.assertTrue(delete_prompt.resolve_delete_after_sync("RQP Live"))

        update.assert_not_called()
        self.assertEqual(
            preferences.delete_synced_files_from_device,
            settings.DELETE_SYNCED_FILES_ASK,
        )


if __name__ == "__main__":
    unittest.main()
