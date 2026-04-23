import copy
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

import store
from utils import preferences
from utils.postprocess import get_postprocessors
from utils.translation import _


class TestMainWindowSettingsFileLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from gui.main_window import MainWindow
        cls.main_window_class = MainWindow

    def setUp(self):
        self.preferences_snapshot = {
            key: copy.deepcopy(preferences.__dict__[key])
            for key in preferences._DEFAULTS
        }
        self.original_preferences_file_path = preferences.preferences_file_path
        self.original_store_selected_directory = store.selected_directory
        self.original_store_profiles = store.profiles

        with patch.object(self.main_window_class, "on_directory_selected"), \
             patch("gui.main_window.SerialWidget.scan_devices"):
            self.window = self.main_window_class()

        self.window.refresh_plot = MagicMock()
        self.window.profile_widget.set_toolbar_visible = MagicMock()
        self.window.serial_widget.view.model.applyFilter = MagicMock()

    def tearDown(self):
        self.window.close()
        for widget in QApplication.topLevelWidgets():
            if widget is not self.window and isinstance(widget, QWidget):
                widget.close()

        for key, value in self.preferences_snapshot.items():
            preferences.__dict__[key] = value
        preferences.preferences_file_path = self.original_preferences_file_path
        store.selected_directory = self.original_store_selected_directory
        store.profiles = self.original_store_profiles

    def test_file_menu_contains_load_settings_action(self):
        self.assertEqual(self.window.load_settings_file_action.text(), _("MENU_BAR_LOAD_SETTINGS_FILE"))
        self.assertIs(self.window.load_settings_file_action.parent(), self.window)

    def test_load_settings_file_from_missing_path_creates_defaults_and_refreshes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "new", "prefs.json")

            result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            self.assertTrue(os.path.exists(path))
            self.window.refresh_plot.assert_called_once()
            self.window.profile_widget.set_toolbar_visible.assert_called_once_with(preferences.show_plot_toolbar)
            self.window.serial_widget.view.model.applyFilter.assert_called_once()

    def test_invalid_file_prompts_and_cancel_keeps_current_preferences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "invalid.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            preferences.distance_unit = "cm"
            current_path = preferences.get_preferences_file_path()

            with patch("gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
                result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_INVALID)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.get_preferences_file_path(), current_path)
            self.window.refresh_plot.assert_not_called()
            question.assert_called_once()

    def test_invalid_file_confirm_overwrite_closes_settings_window_and_refreshes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "invalid.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            settings_window = MagicMock()
            self.window.settings_window = settings_window

            with patch("gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            settings_window.close.assert_called_once()
            self.assertIsNone(self.window.settings_window)
            self.window.refresh_plot.assert_called_once()
            self.window.profile_widget.set_toolbar_visible.assert_called_once_with(preferences.show_plot_toolbar)
            self.window.serial_widget.view.model.applyFilter.assert_called_once()
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["distance_unit"], preferences.distance_unit)

    def test_apply_loaded_preferences_syncs_view_menu_checkboxes(self):
        preferences.show_all_com_ports = True
        preferences.show_plot_toolbar = False
        preferences.recalculate_mean = False

        self.window.apply_loaded_preferences()

        self.assertTrue(self.window.view_menu_checkboxes["show_all_com_ports"].isChecked())
        self.assertFalse(self.window.view_menu_checkboxes["show_plot_toolbar"].isChecked())
        self.assertFalse(self.window.view_menu_checkboxes["recalculate_mean"].isChecked())

    def test_apply_loaded_preferences_syncs_postprocessor_states(self):
        postprocessors = get_postprocessors()
        module_name = next(iter(postprocessors))
        preferences.enabled_postprocessors = []

        self.window.apply_loaded_preferences()

        self.assertFalse(postprocessors[module_name].enabled)
        self.assertFalse(self.window.postprocessor_checkboxes[module_name].isChecked())
        self.assertEqual(self.window.postprocess_manager.enabled_postprocessors, [])

    def test_directory_name_initialized_before_load_settings_file(self):
        self.assertIsNone(self.window.directory_name)

    def test_load_settings_file_from_path_without_prior_directory_selection(self):
        # Verifies no crash (AttributeError on directory_name / refresh_plot guard) occurs
        # when load is triggered before any directory is selected.
        self.window.refresh_plot = self.main_window_class.refresh_plot.__get__(self.window)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "prefs.json")
            result = self.window.load_settings_file_from_path(path)
            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)


if __name__ == "__main__":
    unittest.main()
