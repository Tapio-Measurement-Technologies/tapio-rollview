"""
Utilities for parsing and validating excluded regions format.
Format: "11-90,5-8" means exclude the given ranges.
"""
import re

import numpy as np
import settings


_RANGE_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*-\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


def _clamp(value, lower, upper):
    return max(lower, min(value, upper))


def scale_excluded_ranges(excluded_ranges, factor):
    if factor == 1.0:
        return excluded_ranges
    return [(start * factor, end * factor) for start, end in excluded_ranges]


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
    if not regions_str or not regions_str.strip():
        return []

    regions_str = regions_str.strip()
    ranges = []

    for range_str in regions_str.split(','):
        range_str = range_str.strip()
        if not range_str:
            continue

        match = _RANGE_RE.fullmatch(range_str)
        if not match:
            raise ValueError(f"Invalid range format '{range_str}'. Expected format: 'start-end'")

        try:
            start_value = float(match.group(1))
            end_value = float(match.group(2))
        except ValueError:
            raise ValueError(f"Invalid number in range '{range_str}'")

        if start_value > end_value:
            start_value, end_value = end_value, start_value

        if start_value == end_value:
            continue

        ranges.append((start_value, end_value))

    return ranges


def _get_excluded_ranges_indices_relative(n, excluded_ranges):
    excluded_ranges_idx = []
    for start_pct, end_pct in excluded_ranges:
        start_pct = _clamp(start_pct, 0.0, 100.0)
        end_pct = _clamp(end_pct, 0.0, 100.0)
        start_idx = int(n * start_pct / 100)
        end_idx = int(n * end_pct / 100)
        start_idx = max(0, min(start_idx, n))
        end_idx = max(0, min(end_idx, n))
        if start_idx < end_idx:
            excluded_ranges_idx.append((start_idx, end_idx))
    return excluded_ranges_idx


def _get_excluded_ranges_indices_absolute(distances, excluded_ranges):
    if distances is None or len(distances) == 0:
        return []

    distances = np.asarray(distances, dtype=float)
    profile_start = float(distances[0])
    profile_end = float(distances[-1])
    excluded_ranges_idx = []

    for start_value, end_value in excluded_ranges:
        start_value = _clamp(start_value, profile_start, profile_end)
        end_value = _clamp(end_value, profile_start, profile_end)
        start_idx = int(np.searchsorted(distances, start_value, side='left'))
        end_idx = int(np.searchsorted(distances, end_value, side='right'))
        start_idx = max(0, min(start_idx, len(distances)))
        end_idx = max(0, min(end_idx, len(distances)))
        if start_idx < end_idx:
            excluded_ranges_idx.append((start_idx, end_idx))

    return excluded_ranges_idx


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

    if mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
        excluded_ranges = scale_excluded_ranges(excluded_ranges, absolute_scale)

    distances = np.asarray(distances, dtype=float)
    profile_start = float(distances[0])
    profile_end = float(distances[-1])
    profile_span = profile_end - profile_start
    visual_ranges = []

    for start_value, end_value in excluded_ranges:
        if mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
            start = _clamp(start_value, profile_start, profile_end)
            end = _clamp(end_value, profile_start, profile_end)
        else:
            start_pct = _clamp(start_value, 0.0, 100.0)
            end_pct = _clamp(end_value, 0.0, 100.0)
            start = profile_start + profile_span * start_pct / 100.0
            end = profile_start + profile_span * end_pct / 100.0

        visual_ranges.append((start, end))

    return visual_ranges


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

    if mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
        excluded_ranges = scale_excluded_ranges(excluded_ranges, absolute_scale)
        excluded_ranges_idx = _get_excluded_ranges_indices_absolute(distances, excluded_ranges)
    else:
        excluded_ranges_idx = _get_excluded_ranges_indices_relative(n, excluded_ranges)

    mask = np.ones(n, dtype=bool)
    for start_idx, end_idx in excluded_ranges_idx:
        mask[start_idx:end_idx] = False

    included_data = data[mask]

    return included_data, excluded_ranges_idx
