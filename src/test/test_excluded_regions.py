import unittest

import numpy as np

import settings
from utils.excluded_regions import (
    get_included_samples,
    get_visual_excluded_ranges,
    parse_excluded_regions,
)


class TestExcludedRegions(unittest.TestCase):
    def test_parse_excluded_regions_accepts_signed_ranges(self):
        ranges = parse_excluded_regions("-10-20, 90-110")

        self.assertEqual(ranges, [(-10.0, 20.0), (90.0, 110.0)])

    def test_relative_excluded_regions_are_clamped_to_profile_span(self):
        data = np.arange(10)

        included_data, excluded_ranges = get_included_samples(
            data,
            "-10-20,80-150",
            mode=settings.EXCLUDED_REGIONS_MODE_RELATIVE,
        )

        np.testing.assert_array_equal(included_data, np.array([2, 3, 4, 5, 6, 7]))
        self.assertEqual(excluded_ranges, [(0, 2), (8, 10)])

    def test_absolute_excluded_regions_are_clamped_to_distance_span(self):
        data = np.arange(10)
        distances = np.arange(10, dtype=float)

        included_data, excluded_ranges = get_included_samples(
            data,
            "-5-2.5,8-20",
            mode=settings.EXCLUDED_REGIONS_MODE_ABSOLUTE,
            distances=distances,
        )

        np.testing.assert_array_equal(included_data, np.array([3, 4, 5, 6, 7]))
        self.assertEqual(excluded_ranges, [(0, 3), (8, 10)])

    def test_visual_absolute_excluded_regions_clamp_to_profile_endpoints(self):
        distances = np.linspace(0.0, 10.0, 11)

        visual_ranges = get_visual_excluded_ranges(
            "20-80",
            mode=settings.EXCLUDED_REGIONS_MODE_ABSOLUTE,
            distances=distances,
        )

        self.assertEqual(visual_ranges, [(10.0, 10.0)])

    def test_visual_relative_excluded_regions_use_profile_span(self):
        distances = np.linspace(0.0, 10.0, 11)

        visual_ranges = get_visual_excluded_ranges(
            "20-80",
            mode=settings.EXCLUDED_REGIONS_MODE_RELATIVE,
            distances=distances,
        )

        self.assertEqual(visual_ranges, [(2.0, 8.0)])


if __name__ == "__main__":
    unittest.main()
