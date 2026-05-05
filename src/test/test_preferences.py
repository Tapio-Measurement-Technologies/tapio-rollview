import unittest
import copy
import json
import os
import tempfile

import settings
from utils.highlighted_regions import (
    DISTANCE_HIGHLIGHT_MODE_RELATIVE,
    DistanceHighlightRegion,
    normalize_distance_highlight_regions,
    serialize_distance_highlight_regions,
)
from utils import preferences
from utils.preferences import _normalize_alert_limits


class TestPreferences(unittest.TestCase):
    def setUp(self):
        self.snapshot = {key: copy.deepcopy(preferences.__dict__[key]) for key in preferences._DEFAULTS}
        self.original_preferences_file_path = preferences.preferences_file_path

    def tearDown(self):
        for key, value in self.snapshot.items():
            preferences.__dict__[key] = value
        preferences.preferences_file_path = self.original_preferences_file_path

    def test_missing_alert_limit_defaults_are_restored(self):
        legacy_limits = [
            {
                "name": "mean_g",
                "units": "g",
                "min": 1.0,
                "max": 5.0,
            }
        ]

        normalized_limits = _normalize_alert_limits(legacy_limits)
        normalized_names = [limit["name"] for limit in normalized_limits]

        self.assertIn("slope_deg", normalized_names)

        slope_limit = next(limit for limit in normalized_limits if limit["name"] == "slope_deg")
        self.assertEqual(slope_limit["units"], "g/RL")
        self.assertIsNone(slope_limit["min"])
        self.assertIsNone(slope_limit["max"])

        mean_limit = next(limit for limit in normalized_limits if limit["name"] == "mean_g")
        self.assertEqual(mean_limit["min"], 1.0)
        self.assertEqual(mean_limit["max"], 5.0)

    def test_custom_extra_alert_limits_are_ignored(self):
        custom_limit = {
            "name": "custom_stat",
            "units": "arb",
            "min": 2.0,
            "max": 3.0,
        }

        normalized_limits = _normalize_alert_limits([custom_limit])

        self.assertNotIn(custom_limit, normalized_limits)
        self.assertEqual(len(normalized_limits), len(settings.ALERT_LIMITS_DEFAULT))

    def test_distance_highlight_regions_round_trip_through_normalizers(self):
        regions = [DistanceHighlightRegion(start=1.0, end=2.0, mode=DISTANCE_HIGHLIGHT_MODE_RELATIVE, color="tab:blue")]

        saved_value = serialize_distance_highlight_regions(regions)
        loaded_value = normalize_distance_highlight_regions(saved_value)

        self.assertEqual(loaded_value, regions)

    def test_load_preferences_from_valid_alternate_file_switches_active_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "custom.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump({"distance_unit": "in", "show_plot_toolbar": False}, handle)

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.get_preferences_file_path(), custom_path)
            self.assertEqual(preferences.distance_unit, "in")
            self.assertFalse(preferences.show_plot_toolbar)

    def test_update_preferences_writes_to_loaded_file_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_path = os.path.join(tmpdir, "default.json")
            alternate_path = os.path.join(tmpdir, "alternate.json")
            with open(default_path, "w", encoding="utf-8") as handle:
                json.dump({"distance_unit": "m"}, handle)
            with open(alternate_path, "w", encoding="utf-8") as handle:
                json.dump({"distance_unit": "cm"}, handle)

            preferences.preferences_file_path = default_path
            result = preferences.load_preferences_from_file(alternate_path)
            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)

            preferences.update_preferences({"distance_unit": "in"})

            with open(default_path, "r", encoding="utf-8") as handle:
                default_data = json.load(handle)
            with open(alternate_path, "r", encoding="utf-8") as handle:
                alternate_data = json.load(handle)

            self.assertEqual(default_data["distance_unit"], "m")
            self.assertEqual(alternate_data["distance_unit"], "in")

    def test_missing_file_is_created_with_defaults_and_activated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "nested", "new-preferences.json")

            result = preferences.load_preferences_from_file(missing_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            self.assertTrue(os.path.exists(missing_path))
            self.assertEqual(preferences.get_preferences_file_path(), missing_path)
            with open(missing_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["distance_unit"], settings.DISTANCE_UNIT_DEFAULT)

    def test_empty_file_returns_empty_status_without_changing_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_path = os.path.join(tmpdir, "empty.json")
            with open(empty_path, "w", encoding="utf-8") as handle:
                handle.write("   ")

            preferences.preferences_file_path = os.path.join(tmpdir, "active.json")
            preferences.distance_unit = "cm"

            result = preferences.load_preferences_from_file(empty_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_EMPTY)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.get_preferences_file_path(), os.path.join(tmpdir, "active.json"))

    def test_invalid_file_returns_invalid_status_without_changing_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_path = os.path.join(tmpdir, "invalid.json")
            with open(invalid_path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            preferences.preferences_file_path = os.path.join(tmpdir, "active.json")
            preferences.distance_unit = "cm"

            result = preferences.load_preferences_from_file(invalid_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_INVALID)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.get_preferences_file_path(), os.path.join(tmpdir, "active.json"))

    def test_overwrite_preferences_file_with_defaults_activates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_path = os.path.join(tmpdir, "invalid.json")
            with open(invalid_path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            preferences.distance_unit = "in"

            result = preferences.overwrite_preferences_file_with_defaults(invalid_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            self.assertEqual(preferences.get_preferences_file_path(), invalid_path)
            self.assertEqual(preferences.distance_unit, settings.DISTANCE_UNIT_DEFAULT)
            with open(invalid_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["distance_unit"], settings.DISTANCE_UNIT_DEFAULT)

    def test_partial_json_uses_defaults_for_missing_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "partial.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump({"distance_unit": "cm"}, handle)

            preferences.show_spectrum = True

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.show_spectrum, settings.SHOW_SPECTRUM_DEFAULT)

    def test_invalid_preference_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "invalid-values.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "enabled_postprocessors": None,
                        "locale": "missing-locale",
                        "show_plot_toolbar": "false",
                        "show_spectrum": [],
                        "pinned_serial_ports": "COM1",
                        "distance_unit": "yards",
                        "excluded_regions": "bad-range",
                        "excluded_regions_mode": "bad-mode",
                        "default_y_axis_scaling": "bad-scaling",
                        "y_lim_low_override": "5.5",
                        "y_lim_high_override": "nan",
                        "band_pass_high": "fast",
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.enabled_postprocessors, settings.DEFAULT_ENABLED_POSTPROCESSORS)
            self.assertEqual(preferences.locale, settings.LOCALE_DEFAULT)
            self.assertFalse(preferences.show_plot_toolbar)
            self.assertEqual(preferences.show_spectrum, settings.SHOW_SPECTRUM_DEFAULT)
            self.assertEqual(preferences.pinned_serial_ports, settings.PINNED_SERIAL_PORTS_DEFAULT)
            self.assertEqual(preferences.distance_unit, settings.DISTANCE_UNIT_DEFAULT)
            self.assertEqual(preferences.excluded_regions, settings.EXCLUDED_REGIONS_DEFAULT)
            self.assertEqual(preferences.excluded_regions_mode, settings.EXCLUDED_REGIONS_MODE_DEFAULT)
            self.assertEqual(preferences.default_y_axis_scaling, settings.Y_AXIS_SCALING_DEFAULT)
            self.assertEqual(preferences.y_lim_low_override, 5.5)
            self.assertEqual(preferences.y_lim_high_override, settings.Y_LIM_HIGH_OVERRIDE_DEFAULT)
            self.assertEqual(preferences.band_pass_high, settings.BAND_PASS_HIGH_DEFAULT)

    def test_invalid_cross_field_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "bad-cross-field-values.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "band_pass_low": 50,
                        "band_pass_high": 10,
                        "y_lim_low_override": 20,
                        "y_lim_high_override": 10,
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.band_pass_low, settings.BAND_PASS_LOW_DEFAULT)
            self.assertEqual(preferences.band_pass_high, 10)
            self.assertEqual(preferences.y_lim_low_override, settings.Y_LIM_LOW_OVERRIDE_DEFAULT)
            self.assertEqual(preferences.y_lim_high_override, settings.Y_LIM_HIGH_OVERRIDE_DEFAULT)

    def test_band_pass_high_outside_supported_range_uses_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "bad-band-pass.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump({"band_pass_high": 1000}, handle)

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.band_pass_high, settings.BAND_PASS_HIGH_DEFAULT)

    def test_legacy_excluded_regions_enabled_string_false_keeps_mode_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "legacy.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump({"excluded_regions_enabled": "false"}, handle)

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.excluded_regions_mode, settings.EXCLUDED_REGIONS_MODE_NONE)
            self.assertFalse(preferences.excluded_regions_enabled)

    def test_invalid_alert_limit_numbers_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "alert-limits.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "alert_limits": [
                            {
                                "name": "mean_g",
                                "units": "g",
                                "min": "bad",
                                "max": "2.5",
                            }
                        ]
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            mean_limit = next(limit for limit in preferences.alert_limits if limit["name"] == "mean_g")
            self.assertIsNone(mean_limit["min"])
            self.assertEqual(mean_limit["max"], 2.5)

    def test_invalid_alert_limit_units_and_ranges_use_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "bad-alert-limit-values.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "alert_limits": [
                            {
                                "name": "slope_deg",
                                "units": "wrong",
                                "min": 10,
                                "max": -10,
                            }
                        ]
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            slope_limit = next(limit for limit in preferences.alert_limits if limit["name"] == "slope_deg")
            self.assertEqual(slope_limit["units"], "g/RL")
            self.assertIsNone(slope_limit["min"])
            self.assertIsNone(slope_limit["max"])

    def test_update_preferences_does_not_save_unknown_alert_limit_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preferences.preferences_file_path = os.path.join(tmpdir, "prefs.json")

            preferences.update_preferences(
                {
                    "alert_limits": [
                        {
                            "name": "slope_dag",
                            "units": "g/RL",
                            "min": -10,
                            "max": 10,
                        },
                        {
                            "name": "slope_deg",
                            "units": "g/RL",
                            "min": -5,
                            "max": 5,
                        },
                    ]
                }
            )

            self.assertNotIn("slope_dag", [limit["name"] for limit in preferences.alert_limits])
            with open(preferences.preferences_file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertNotIn("slope_dag", [limit["name"] for limit in data["alert_limits"]])
            slope_limit = next(limit for limit in data["alert_limits"] if limit["name"] == "slope_deg")
            self.assertEqual(slope_limit["min"], -5.0)
            self.assertEqual(slope_limit["max"], 5.0)

    def test_malformed_slope_alert_limit_name_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "bad-slope-key.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "alert_limits": [
                            {
                                "name": "slope_dag",
                                "units": "g/RL",
                                "min": "-10",
                                "max": "10",
                            }
                        ]
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertNotIn("slope_dag", [limit["name"] for limit in preferences.alert_limits])
            slope_limit = next(limit for limit in preferences.alert_limits if limit["name"] == "slope_deg")
            self.assertEqual(slope_limit["units"], "g/RL")
            self.assertIsNone(slope_limit["min"])
            self.assertIsNone(slope_limit["max"])

    def test_unknown_json_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "unknown-key.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "distance_unit": "in",
                        "future_setting": {"unexpected": True},
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(preferences.distance_unit, "in")
            self.assertNotIn("future_setting", preferences.__dict__)

    def test_top_level_json_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "list.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump([], handle)

            preferences.preferences_file_path = os.path.join(tmpdir, "active.json")
            preferences.distance_unit = "cm"

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_INVALID)
            self.assertIn("Top-level JSON must be an object", result.error)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.get_preferences_file_path(), os.path.join(tmpdir, "active.json"))

    def test_invalid_highlight_region_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "bad-highlights.json")
            with open(custom_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "distance_highlight_regions": [
                            {"start": "bad", "end": 2, "mode": "absolute", "color": "tab:blue"},
                            {"start": 1, "end": 2, "mode": "absolute", "color": "tab:red"},
                        ],
                        "hardness_highlight_regions": [
                            {"mode": "fixed", "color": "tab:blue", "min_value": "bad", "max_value": 2},
                            {"mode": "mean_offset_absolute", "color": "tab:green", "lower_offset": -1},
                        ],
                    },
                    handle,
                )

            result = preferences.load_preferences_from_file(custom_path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_LOADED)
            self.assertEqual(len(preferences.distance_highlight_regions), 1)
            self.assertEqual(preferences.distance_highlight_regions[0].color, "tab:red")
            self.assertEqual(len(preferences.hardness_highlight_regions), 1)
            self.assertEqual(preferences.hardness_highlight_regions[0].color, "tab:green")

if __name__ == "__main__":
    unittest.main()
