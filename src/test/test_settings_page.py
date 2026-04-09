import unittest

from PySide6.QtWidgets import QApplication

import settings
from gui.settings import AdvancedSettingsPage, GeneralSettingsPage
from utils import preferences


class TestAdvancedSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        self.original_distance_unit = preferences.distance_unit

        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_RELATIVE
        preferences.excluded_regions = ""
        preferences.distance_unit = settings.DISTANCE_UNIT_DEFAULT

        self.page = AdvancedSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions
        preferences.distance_unit = self.original_distance_unit

    def _set_mode(self, mode):
        self.page.excluded_regions_mode_selector.setCurrentText(
            self.page.excluded_regions_modes[mode]
        )

    def test_switching_relative_to_absolute_keeps_text_unchanged(self):
        self.page.excluded_regions_input.setText("20-80")

        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)

        self.assertEqual(self.page.excluded_regions_input.text(), "20-80")

    def test_switching_absolute_to_relative_keeps_text_unchanged(self):
        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)
        self.page.excluded_regions_input.setText("2-8")

        self._set_mode(settings.EXCLUDED_REGIONS_MODE_RELATIVE)

        self.assertEqual(self.page.excluded_regions_input.text(), "2-8")

    def test_reopening_absolute_mode_preserves_same_numbers(self):
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_ABSOLUTE
        preferences.excluded_regions = "1-2"
        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)

        preferences.distance_unit = "in"
        reopened_page = AdvancedSettingsPage()
        self.addCleanup(reopened_page.close)

        reopened_page.excluded_regions_mode_selector.setCurrentText(
            reopened_page.excluded_regions_modes[settings.EXCLUDED_REGIONS_MODE_ABSOLUTE]
        )
        self.assertEqual(reopened_page.excluded_regions_input.text(), "1-2")

    def test_reset_to_defaults_populates_advanced_fields_with_defaults(self):
        self.page.band_pass_high_input.setText("5.0")
        self.page.y_lim_low_input.setText("1.0")
        self.page.y_lim_high_input.setText("9.0")
        self.page.show_spectrum_checkbox.setChecked(True)
        self.page.continuous_mode_checkbox.setChecked(True)
        self.page.flip_profiles_checkbox.setChecked(True)
        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)
        self.page.excluded_regions_input.setText("1-2")

        self.page.reset_to_defaults()

        self.assertEqual(
            self.page.band_pass_high_input.text(),
            f"{settings.BAND_PASS_HIGH_DEFAULT:.1f}",
        )
        self.assertEqual(
            self.page.y_axis_scaling_selector.currentText(),
            self.page.y_axis_scaling_modes[settings.Y_AXIS_SCALING_DEFAULT],
        )
        self.assertEqual(self.page.y_lim_low_input.text(), "")
        self.assertEqual(self.page.y_lim_high_input.text(), "")
        self.assertEqual(self.page.show_spectrum_checkbox.isChecked(), settings.SHOW_SPECTRUM_DEFAULT)
        self.assertEqual(self.page.continuous_mode_checkbox.isChecked(), settings.CONTINUOUS_MODE_DEFAULT)
        self.assertEqual(self.page.flip_profiles_checkbox.isChecked(), settings.FLIP_PROFILES_DEFAULT)
        self.assertEqual(
            self.page.excluded_regions_mode_selector.currentText(),
            self.page.excluded_regions_modes[settings.EXCLUDED_REGIONS_MODE_DEFAULT],
        )
        self.assertEqual(self.page.excluded_regions_input.text(), settings.EXCLUDED_REGIONS_DEFAULT)
        self.assertTrue(self.page.apply_button.isEnabled())


class TestGeneralSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_distance_unit = preferences.distance_unit
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        self.original_locale = preferences.locale

        preferences.distance_unit = "m"
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_ABSOLUTE
        preferences.excluded_regions = "1-2"
        preferences.locale = settings.LOCALE_DEFAULT

        self.page = GeneralSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.distance_unit = self.original_distance_unit
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions
        preferences.locale = self.original_locale

    def test_save_settings_converts_absolute_excluded_regions_when_distance_unit_changes(self):
        self.page.distance_unit_selector.setCurrentText(self.page.distance_units["in"])

        self.page.save_settings()

        self.assertEqual(preferences.distance_unit, "in")
        self.assertEqual(preferences.excluded_regions, "1-2")


if __name__ == "__main__":
    unittest.main()
