import unittest
import copy

from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

import settings
from gui.settings import (
    AlertLimitSettingsPage,
    AdvancedSettingsPage,
    DistanceHighlightsSettingsPage,
    GeneralSettingsPage,
    HardnessHighlightsSettingsPage,
    SettingsWindow,
)
from utils.highlighted_regions import (
    FixedHardnessHighlightRegion,
    DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
    DistanceHighlightRegion,
)
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


class TestAlertLimitSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_alert_limits = preferences.alert_limits
        preferences.alert_limits = [
            copy.deepcopy(settings.ALERT_LIMITS_DEFAULT[0]) | {"min": 1.0, "max": 2.0},
        ]
        self.page = AlertLimitSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.alert_limits = self.original_alert_limits

    def test_alert_limit_row_uses_card_layout_and_fixed_inputs(self):
        row = self.page.setting_widgets[0]

        self.assertIsInstance(row, QFrame)
        self.assertEqual(row.min_input.maximumWidth(), row.INPUT_WIDTH)
        self.assertEqual(row.max_input.maximumWidth(), row.INPUT_WIDTH)


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

    def test_distance_unit_selector_includes_centimeters(self):
        self.assertIn("cm", self.page.distance_units)
        self.assertEqual(self.page.distance_units["cm"], "Centimeters (cm)")


class TestDistanceHighlightsSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_distance_highlight_regions = preferences.distance_highlight_regions
        preferences.distance_highlight_regions = []
        self.page = DistanceHighlightsSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.distance_highlight_regions = self.original_distance_highlight_regions

    def test_add_distance_highlight_creates_row(self):
        self.assertEqual(len(self.page.rows), 0)
        self.assertFalse(self.page.empty_state_card.isHidden())

        self.page.add_empty_row()

        self.assertEqual(len(self.page.rows), 1)
        self.assertEqual(self.page.rows[0].start_input.text(), "")
        self.assertEqual(self.page.rows[0].end_input.text(), "")
        self.assertTrue(self.page.empty_state_card.isHidden())
        self.assertTrue(self.page.apply_button.isEnabled())

    def test_distance_page_uses_scroll_area_for_rows(self):
        self.assertIsInstance(self.page.rows_scroll_area, QScrollArea)
        self.assertTrue(self.page.rows_scroll_area.widgetResizable())
        self.assertEqual(self.page.rows_scroll_area.frameShape(), QFrame.Shape.NoFrame)

    def test_save_settings_persists_valid_distance_regions(self):
        self.page.add_empty_row()
        row = self.page.rows[0]
        row.start_input.setText("1")
        row.end_input.setText("2")
        row.mode_selector.setCurrentText(row.modes[DISTANCE_HIGHLIGHT_MODE_ABSOLUTE])

        self.page.save_settings()

        self.assertEqual(
            preferences.distance_highlight_regions,
            [DistanceHighlightRegion(start=1.0, end=2.0, mode="absolute", color="tab:blue")],
        )
        self.assertFalse(self.page.apply_button.isEnabled())

    def test_save_settings_supports_open_ended_distance_region(self):
        self.page.add_empty_row()
        row = self.page.rows[0]
        row.end_input.setText("20")

        self.page.save_settings()

        self.assertEqual(preferences.distance_highlight_regions[0].start, float("-inf"))
        self.assertEqual(preferences.distance_highlight_regions[0].end, 20.0)

    def test_invalid_region_blocks_save(self):
        self.page.add_empty_row()
        row = self.page.rows[0]
        row.start_input.setText("abc")
        row.end_input.setText("2")

        self.page.save_settings()

        self.assertEqual(preferences.distance_highlight_regions, [])
        self.assertFalse(self.page.error_label.isHidden())

    def test_reset_to_defaults_clears_rows(self):
        self.page.add_empty_row()

        self.page.reset_to_defaults()

        self.assertEqual(len(self.page.rows), 0)
        self.assertFalse(self.page.empty_state_card.isHidden())
        self.assertTrue(self.page.apply_button.isEnabled())

    def test_distance_region_row_uses_card_frame_and_color_icons(self):
        self.page.add_empty_row()

        row = self.page.rows[0]

        self.assertIsInstance(row, QFrame)
        self.assertEqual(row.range_label.text(), "Range")
        self.assertEqual(row.range_separator.text(), "–")
        self.assertEqual(row.mode_label.text(), "Mode")
        self.assertEqual(row.color_label.text(), "Color")
        self.assertFalse(row.color_selector.itemIcon(0).isNull())


class TestHardnessHighlightsSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_hardness_highlight_regions = preferences.hardness_highlight_regions
        preferences.hardness_highlight_regions = []
        self.page = HardnessHighlightsSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.hardness_highlight_regions = self.original_hardness_highlight_regions

    def test_hardness_region_row_updates_labels_for_mode(self):
        self.page.add_empty_row()

        row = self.page.rows[0]
        row.mode_selector.setCurrentText(row.modes["mean_offset_absolute"])

        self.assertEqual(row.range_label.text(), "Range")
        self.assertEqual(row.range_separator.text(), "–")

    def test_save_settings_persists_valid_hardness_regions(self):
        self.page.add_empty_row()
        row = self.page.rows[0]
        row.first_input.setText("1")
        row.second_input.setText("2")

        self.page.save_settings()

        self.assertEqual(
            preferences.hardness_highlight_regions,
            [FixedHardnessHighlightRegion(color="tab:blue", min_value=1.0, max_value=2.0)],
        )


class TestSettingsWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_window_has_distance_and_hardness_pages(self):
        window = SettingsWindow()
        try:
            page_names = [window.list_widget.item(i).text() for i in range(window.list_widget.count())]
            self.assertIn("Distance highlights", page_names)
            self.assertIn("Hardness highlights", page_names)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
