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
        self.original_store_selected_profile = store.selected_profile
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
        store.selected_profile = self.original_store_selected_profile
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

    def test_apply_loaded_preferences_drops_unknown_postprocessor_names(self):
        postprocessors = get_postprocessors()
        module_name = next(iter(postprocessors))
        preferences.enabled_postprocessors = [module_name, "missing_postprocessor"]

        self.window.apply_loaded_preferences()

        self.assertEqual(preferences.enabled_postprocessors, [module_name])
        self.assertTrue(postprocessors[module_name].enabled)
        self.assertTrue(self.window.postprocessor_checkboxes[module_name].isChecked())

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

    def test_statistics_directory_selection_updates_app_plot_and_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected_directory = os.path.join(tmpdir, "roll-1")
            os.mkdir(selected_directory)
            self.window.on_directory_selected = MagicMock()
            self.window.statistics_analysis_widget.highlight_point = MagicMock()

            signal_block_states = []

            def capture_signal_block_state(path):
                signal_block_states.append(self.window.directory_view.signalsBlocked())

            self.window.directory_view.select_directory_by_path = MagicMock(side_effect=capture_signal_block_state)

            self.window.on_statistics_directory_selected(selected_directory)

            self.window.on_directory_selected.assert_called_once_with(selected_directory)
            self.window.statistics_analysis_widget.highlight_point.assert_called_once_with(selected_directory)
            self.window.directory_view.select_directory_by_path.assert_called_once_with(selected_directory)
            self.assertEqual(signal_block_states, [True])

    def test_directory_selection_clears_selected_profile_when_directory_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_directory = os.path.join(tmpdir, "old")
            new_directory = os.path.join(tmpdir, "new")
            os.mkdir(old_directory)
            os.mkdir(new_directory)

            store.selected_directory = old_directory
            store.selected_profile = "selected.prof"
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.update_plot = MagicMock()

            self.window.on_directory_selected(new_directory)

            self.assertIsNone(store.selected_profile)

    def test_directory_selection_keeps_selected_profile_when_directory_is_same(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.selected_directory = tmpdir
            store.selected_profile = "selected.prof"
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.update_plot = MagicMock()

            self.window.on_directory_selected(tmpdir)

            self.assertEqual(store.selected_profile, "selected.prof")

    def test_root_directory_change_shows_empty_profile_state_when_root_has_no_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.selected_directory = None
            store.selected_profile = "selected.prof"
            store.profiles = ["stale"]
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()
            self.window.profile_widget.show_no_profile_files_message = MagicMock()

            self.window.on_root_directory_changed(tmpdir)

            self.assertEqual(store.root_directory, tmpdir)
            self.assertIsNone(store.selected_directory)
            self.assertIsNone(store.selected_profile)
            self.assertEqual(store.profiles, [])
            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.clear_plot_display.assert_not_called()
            self.window.profile_widget.show_no_profile_files_message.assert_called_once_with(
                os.path.basename(tmpdir)
            )

    def test_root_directory_change_does_not_blank_plot_when_profile_folders_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "roll-1"))
            store.selected_directory = None
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_root_directory_changed(tmpdir)

            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.clear_plot_display.assert_not_called()

    def test_directory_contents_changed_clears_plot_when_last_folder_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.root_directory = tmpdir
            store.selected_directory = os.path.join(tmpdir, "deleted")
            store.selected_profile = "selected.prof"
            store.profiles = ["stale"]
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_directory_contents_changed()

            self.assertIsNone(store.selected_directory)
            self.assertIsNone(store.selected_profile)
            self.assertEqual(store.profiles, [])
            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.clear_plot_display.assert_called_once()

    def test_directory_contents_changed_selects_first_folder_when_selected_folder_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "remaining"))
            store.root_directory = tmpdir
            store.selected_directory = os.path.join(tmpdir, "deleted")
            self.window.directory_view.select_first_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_directory_contents_changed()

            self.window.directory_view.select_first_directory.assert_called_once()
            self.window.profile_widget.clear_plot_display.assert_not_called()

    def test_file_transfer_finished_refreshes_directory_dates_before_postprocessing(self):
        folder_paths = ["/tmp/roll-1"]
        call_order = []
        self.window.directory_view.refresh_directory_dates = MagicMock(
            side_effect=lambda paths: call_order.append("refresh")
        )
        self.window.postprocess_manager.run_postprocessors = MagicMock(
            side_effect=lambda paths: call_order.append("postprocess")
        )
        self.window.on_directory_contents_changed = MagicMock(
            side_effect=lambda: call_order.append("reload")
        )

        self.window.on_file_transfer_finished(folder_paths)

        self.window.directory_view.refresh_directory_dates.assert_called_once_with(folder_paths)
        self.window.postprocess_manager.run_postprocessors.assert_called_once_with(folder_paths)
        self.window.on_directory_contents_changed.assert_called_once()
        self.assertEqual(call_order, ["refresh", "postprocess", "reload"])


if __name__ == "__main__":
    unittest.main()
