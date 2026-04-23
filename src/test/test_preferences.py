import unittest

import settings
from utils.highlighted_regions import (
    DISTANCE_HIGHLIGHT_MODE_RELATIVE,
    DistanceHighlightRegion,
    normalize_distance_highlight_regions,
    serialize_distance_highlight_regions,
)
from utils.preferences import _normalize_alert_limits


class TestPreferences(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
