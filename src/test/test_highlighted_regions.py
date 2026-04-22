import unittest

import numpy as np
import math

from utils.highlighted_regions import (
    HighlightedRegion,
    parse_highlighted_region,
    get_visual_highlighted_regions,
    normalize_highlighted_regions,
    serialize_highlighted_regions,
)


class TestHighlightedRegions(unittest.TestCase):
    def test_normalize_highlighted_regions_skips_invalid_entries(self):
        normalized = normalize_highlighted_regions([
            {"start": 3, "end": 1, "mode": "relative", "color": "tab:red"},
            {"start": 1, "end": 2, "mode": "bad", "color": "tab:red"},
            {"start": 1, "end": 2, "mode": "absolute", "color": "bad"},
        ])

        self.assertEqual(
            normalized,
            [HighlightedRegion(start=1.0, end=3.0, mode="relative", color="tab:red")],
        )

    def test_serialize_highlighted_regions_round_trips(self):
        regions = [HighlightedRegion(start=1.0, end=2.0, mode="absolute", color="tab:blue")]

        serialized = serialize_highlighted_regions(regions)
        normalized = normalize_highlighted_regions(serialized)

        self.assertEqual(normalized, regions)

    def test_visual_highlighted_regions_preserve_color(self):
        regions = [
            HighlightedRegion(start=20.0, end=80.0, mode="relative", color="tab:green"),
            HighlightedRegion(start=12.0, end=20.0, mode="absolute", color="tab:red"),
        ]

        visual_regions = get_visual_highlighted_regions(regions, np.linspace(0.0, 10.0, 11))

        self.assertEqual(visual_regions[0].color, "tab:green")
        self.assertEqual(visual_regions[0].start, 2.0)
        self.assertEqual(visual_regions[0].end, 8.0)
        self.assertEqual(visual_regions[1].color, "tab:red")
        self.assertEqual(visual_regions[1].start, 10.0)
        self.assertEqual(visual_regions[1].end, 10.0)

    def test_parse_highlighted_region_returns_none_for_empty_row(self):
        region = parse_highlighted_region("", "", "relative", "tab:blue")

        self.assertIsNone(region)

    def test_parse_highlighted_region_supports_open_ended_ranges(self):
        region = parse_highlighted_region("", "20", "relative", "tab:blue")

        self.assertEqual(region, HighlightedRegion(start=-math.inf, end=20.0, mode="relative", color="tab:blue"))

    def test_visual_highlighted_regions_clamp_open_ended_ranges(self):
        regions = [HighlightedRegion(start=80.0, end=math.inf, mode="relative", color="tab:blue")]

        visual_regions = get_visual_highlighted_regions(regions, np.linspace(0.0, 10.0, 11))

        self.assertEqual(visual_regions[0].start, 8.0)
        self.assertEqual(visual_regions[0].end, 10.0)


if __name__ == "__main__":
    unittest.main()
