"""
Utilities for parsing and validating excluded regions format.
Format: "11-90,5-8" means exclude the given ranges.
"""

import numpy as np
import settings
from utils.range_utils import (
    NumericRange,
    absolute_ranges_to_indices,
    parse_numeric_ranges,
    ranges_to_visual_coordinates,
    relative_ranges_to_indices,
    scale_numeric_ranges,
)


def scale_excluded_ranges(excluded_ranges, factor):
    numeric_ranges = [NumericRange(start, end) for start, end in excluded_ranges]
    return [numeric_range.as_tuple() for numeric_range in scale_numeric_ranges(numeric_ranges, factor)]


def parse_excluded_regions(regions_str):
    """
    Parse excluded regions string format like '11-90,5-8' into list of range tuples.

    - Accepts reversed ranges (e.g., '90-11' becomes '11-90')
    - Accepts overlapping ranges (e.g., '5-10,8-15' is valid)

    Args:
        regions_str: String format like '11-90,5-8'

    Returns:
        List of tuples [(start1, end1), (start2, end2), ...]

    Raises:
        ValueError: If format is invalid with descriptive error message
    """
    return [numeric_range.as_tuple() for numeric_range in parse_numeric_ranges(regions_str)]


def get_visual_excluded_ranges(excluded_regions_str, mode=None, distances=None, absolute_scale=1.0):
    """Return clamped excluded ranges in the same coordinate system as distances."""
    if distances is None or len(distances) == 0:
        return []

    mode = mode or settings.EXCLUDED_REGIONS_MODE_RELATIVE
    if mode == settings.EXCLUDED_REGIONS_MODE_NONE:
        return []

    try:
        excluded_ranges = parse_excluded_regions(excluded_regions_str)
    except ValueError as e:
        print(f"Warning: Invalid excluded regions format: {e}")
        return []

    if not excluded_ranges:
        return []

    numeric_ranges = [NumericRange(start, end) for start, end in excluded_ranges]
    if mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
        numeric_ranges = scale_numeric_ranges(numeric_ranges, absolute_scale)

    return [
        visual_range.as_tuple()
        for visual_range in ranges_to_visual_coordinates(numeric_ranges, mode, distances)
    ]


def get_included_samples(data, excluded_regions_str, mode=None, distances=None, absolute_scale=1.0):
    """
    Extract samples excluding specified regions.

    Args:
        data: 1D numpy array
        excluded_regions_str: String format like '11-90'
        mode: one of none/relative/absolute
        distances: optional distance axis in meters for absolute mode

    Returns:
        Tuple of (included_data, excluded_ranges_indices) where:
        - included_data: concatenated array of included samples
        - excluded_ranges_indices: list of (start_idx, end_idx) tuples for excluded regions in data indices
    """
    data = np.asarray(data)
    n = len(data)
    if n == 0:
        return data, []

    mode = mode or settings.EXCLUDED_REGIONS_MODE_RELATIVE
    if mode == settings.EXCLUDED_REGIONS_MODE_NONE:
        return data, []

    try:
        excluded_ranges = parse_excluded_regions(excluded_regions_str)
    except ValueError as e:
        print(f"Warning: Invalid excluded regions format: {e}")
        return data, []

    if not excluded_ranges:
        return data, []

    numeric_ranges = [NumericRange(start, end) for start, end in excluded_ranges]
    if mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
        numeric_ranges = scale_numeric_ranges(numeric_ranges, absolute_scale)
        excluded_ranges_idx = absolute_ranges_to_indices(distances, numeric_ranges)
    else:
        excluded_ranges_idx = relative_ranges_to_indices(n, numeric_ranges)

    mask = np.ones(n, dtype=bool)
    for start_idx, end_idx in excluded_ranges_idx:
        mask[start_idx:end_idx] = False

    included_data = data[mask]

    return included_data, excluded_ranges_idx
