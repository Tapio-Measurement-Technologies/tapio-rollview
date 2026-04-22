import unittest

import numpy as np

from utils.range_utils import (
    NumericRange,
    absolute_ranges_to_indices,
    parse_numeric_range,
    parse_numeric_ranges,
    ranges_to_visual_coordinates,
    relative_ranges_to_indices,
)


class TestRangeUtils(unittest.TestCase):
    def test_parse_numeric_ranges_accepts_signed_ranges(self):
        ranges = parse_numeric_ranges("-10-20, 90-110")

        self.assertEqual(ranges, [NumericRange(-10.0, 20.0), NumericRange(90.0, 110.0)])

    def test_parse_numeric_range_normalizes_reversed_range(self):
        numeric_range = parse_numeric_range("20-10")

        self.assertEqual(numeric_range, NumericRange(10.0, 20.0))

    def test_parse_numeric_ranges_drops_zero_length_range(self):
        ranges = parse_numeric_ranges("1-1,2-4")

        self.assertEqual(ranges, [NumericRange(2.0, 4.0)])

    def test_relative_ranges_to_indices_clamps_to_sample_span(self):
        index_ranges = relative_ranges_to_indices(10, [NumericRange(-10.0, 20.0), NumericRange(80.0, 150.0)])

        self.assertEqual(index_ranges, [(0, 2), (8, 10)])

    def test_absolute_ranges_to_indices_clamps_to_distance_span(self):
        distances = np.arange(10, dtype=float)

        index_ranges = absolute_ranges_to_indices(distances, [NumericRange(-5.0, 2.5), NumericRange(8.0, 20.0)])

        self.assertEqual(index_ranges, [(0, 3), (8, 10)])

    def test_ranges_to_visual_coordinates_supports_relative_and_absolute(self):
        distances = np.linspace(0.0, 10.0, 11)

        relative_ranges = ranges_to_visual_coordinates([NumericRange(20.0, 80.0)], "relative", distances)
        absolute_ranges = ranges_to_visual_coordinates([NumericRange(20.0, 80.0)], "absolute", distances)

        self.assertEqual(relative_ranges, [NumericRange(2.0, 8.0)])
        self.assertEqual(absolute_ranges, [NumericRange(10.0, 10.0)])


if __name__ == "__main__":
    unittest.main()
