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

    def test_custom_extra_alert_limits_are_preserved(self):
        custom_limit = {
            "name": "custom_stat",
            "units": "arb",
            "min": 2.0,
            "max": 3.0,
        }

        normalized_limits = _normalize_alert_limits([custom_limit])

        self.assertIn(custom_limit, normalized_limits)
        self.assertEqual(len(normalized_limits), len(settings.ALERT_LIMITS_DEFAULT) + 1)

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

if __name__ == "__main__":
    unittest.main()
