import math
import unittest

import numpy as np

from utils.highlighted_regions import (
    AbsoluteMeanOffsetHardnessHighlightRegion,
    DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
    DISTANCE_HIGHLIGHT_MODE_RELATIVE,
    FixedHardnessHighlightRegion,
    HARDNESS_HIGHLIGHT_MODE_FIXED,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE,
    DistanceHighlightRegion,
    RelativeMeanOffsetHardnessHighlightRegion,
    get_visual_distance_highlight_regions,
    get_visual_hardness_highlight_regions,
    normalize_distance_highlight_regions,
    normalize_hardness_highlight_regions,
    parse_distance_highlight_region,
    parse_hardness_highlight_region,
    serialize_distance_highlight_regions,
    serialize_hardness_highlight_regions,
)


class TestDistanceHighlightedRegions(unittest.TestCase):
    def test_normalize_distance_regions_skips_invalid_entries(self):
        normalized = normalize_distance_highlight_regions([
            {"start": 3, "end": 1, "mode": DISTANCE_HIGHLIGHT_MODE_RELATIVE, "color": "tab:red"},
            {"start": 1, "end": 2, "mode": "bad", "color": "tab:red"},
            {"start": 1, "end": 2, "mode": DISTANCE_HIGHLIGHT_MODE_ABSOLUTE, "color": "bad"},
        ])

        self.assertEqual(
            normalized,
            [DistanceHighlightRegion(start=1.0, end=3.0, mode=DISTANCE_HIGHLIGHT_MODE_RELATIVE, color="tab:red")],
        )

    def test_distance_regions_round_trip_through_normalizers(self):
        regions = [DistanceHighlightRegion(start=1.0, end=2.0, mode=DISTANCE_HIGHLIGHT_MODE_ABSOLUTE, color="tab:blue")]

        saved_value = serialize_distance_highlight_regions(regions)
        loaded_value = normalize_distance_highlight_regions(saved_value)

        self.assertEqual(loaded_value, regions)

    def test_distance_visual_regions_preserve_color(self):
        regions = [
            DistanceHighlightRegion(start=20.0, end=80.0, mode=DISTANCE_HIGHLIGHT_MODE_RELATIVE, color="tab:green"),
            DistanceHighlightRegion(start=12.0, end=20.0, mode=DISTANCE_HIGHLIGHT_MODE_ABSOLUTE, color="tab:red"),
        ]

        visual_regions = get_visual_distance_highlight_regions(regions, np.linspace(0.0, 10.0, 11))

        self.assertEqual(visual_regions[0].color, "tab:green")
        self.assertEqual(visual_regions[0].start, 2.0)
        self.assertEqual(visual_regions[0].end, 8.0)
        self.assertEqual(visual_regions[1].color, "tab:red")
        self.assertEqual(visual_regions[1].start, 10.0)
        self.assertEqual(visual_regions[1].end, 10.0)

    def test_parse_distance_region_returns_none_for_empty_row(self):
        region = parse_distance_highlight_region("", "", DISTANCE_HIGHLIGHT_MODE_RELATIVE, "tab:blue")

        self.assertIsNone(region)

    def test_parse_distance_region_supports_open_ended_ranges(self):
        region = parse_distance_highlight_region("", "20", DISTANCE_HIGHLIGHT_MODE_RELATIVE, "tab:blue")

        self.assertEqual(
            region,
            DistanceHighlightRegion(start=-math.inf, end=20.0, mode=DISTANCE_HIGHLIGHT_MODE_RELATIVE, color="tab:blue"),
        )

    def test_distance_visual_regions_clamp_open_ended_ranges(self):
        regions = [DistanceHighlightRegion(start=80.0, end=math.inf, mode=DISTANCE_HIGHLIGHT_MODE_RELATIVE, color="tab:blue")]

        visual_regions = get_visual_distance_highlight_regions(regions, np.linspace(0.0, 10.0, 11))

        self.assertEqual(visual_regions[0].start, 8.0)
        self.assertEqual(visual_regions[0].end, 10.0)


class TestHardnessHighlightedRegions(unittest.TestCase):
    def test_hardness_regions_round_trip_through_normalizers(self):
        regions = [
            AbsoluteMeanOffsetHardnessHighlightRegion(
                color="tab:orange",
                below_offset=1.0,
                above_offset=2.0,
            )
        ]

        saved_value = serialize_hardness_highlight_regions(regions)
        loaded_value = normalize_hardness_highlight_regions(saved_value)

        self.assertEqual(loaded_value, regions)

    def test_parse_fixed_hardness_region_normalizes_range(self):
        region = parse_hardness_highlight_region("5", "1", HARDNESS_HIGHLIGHT_MODE_FIXED, "tab:red")

        self.assertEqual(
            region,
            FixedHardnessHighlightRegion(color="tab:red", min_value=1.0, max_value=5.0),
        )

    def test_parse_hardness_region_supports_one_sided_mean_offset(self):
        region = parse_hardness_highlight_region("", "2", HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE, "tab:blue")

        self.assertEqual(
            region,
            AbsoluteMeanOffsetHardnessHighlightRegion(
                color="tab:blue",
                below_offset=None,
                above_offset=2.0,
            ),
        )

    def test_visual_hardness_regions_support_fixed_mode(self):
        regions = [
            FixedHardnessHighlightRegion(
                color="tab:green",
                min_value=1.0,
                max_value=3.0,
            )
        ]

        visual_regions = get_visual_hardness_highlight_regions(regions, mean_value=10.0)

        self.assertEqual(visual_regions[0].start, 1.0)
        self.assertEqual(visual_regions[0].end, 3.0)

    def test_visual_hardness_regions_support_asymmetric_absolute_mean_offsets(self):
        regions = [
            AbsoluteMeanOffsetHardnessHighlightRegion(
                color="tab:green",
                below_offset=2.0,
                above_offset=3.0,
            )
        ]

        visual_regions = get_visual_hardness_highlight_regions(regions, mean_value=10.0)

        self.assertEqual(visual_regions[0].start, 8.0)
        self.assertEqual(visual_regions[0].end, 13.0)

    def test_visual_hardness_regions_support_asymmetric_relative_mean_offsets(self):
        regions = [
            RelativeMeanOffsetHardnessHighlightRegion(
                color="tab:green",
                below_percent=10.0,
                above_percent=20.0,
            )
        ]

        visual_regions = get_visual_hardness_highlight_regions(regions, mean_value=-10.0)

        self.assertEqual(visual_regions[0].start, -11.0)
        self.assertEqual(visual_regions[0].end, -8.0)

    def test_visual_hardness_regions_skip_empty_or_zero_height(self):
        empty = parse_hardness_highlight_region("", "", HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE, "tab:blue")
        zero = RelativeMeanOffsetHardnessHighlightRegion(
            color="tab:blue",
            below_percent=10.0,
            above_percent=None,
        )

        self.assertIsNone(empty)
        visual_regions = get_visual_hardness_highlight_regions([zero], mean_value=0.0)
        self.assertEqual(visual_regions, [])


if __name__ == "__main__":
    unittest.main()
