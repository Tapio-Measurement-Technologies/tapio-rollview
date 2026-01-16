"""
Utilities for parsing and validating excluded regions format.
Format: "11-90,5-8" means exclude indices 11-90% and 5-8%
"""
import numpy as np


def parse_excluded_regions(regions_str):
    """
    Parse excluded regions string format like '11-90,5-8' into list of range tuples.

    - Accepts reversed ranges (e.g., '90-11' becomes '11-90')
    - Accepts overlapping ranges (e.g., '5-10,8-15' is valid)
    - Validates that values are between 0-100

    Args:
        regions_str: String format like '11-90,5-8' (percent-based ranges)

    Returns:
        List of tuples [(start1, end1), (start2, end2), ...] in percent format

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

        if '-' not in range_str:
            raise ValueError(f"Invalid range format '{range_str}'. Expected format: 'start-end'")

        parts = range_str.split('-', 1)  # Split only on first dash
        if len(parts) != 2:
            raise ValueError(f"Invalid range format '{range_str}'")

        start, end = parts
        try:
            start_pct = float(start.strip())
            end_pct = float(end.strip())
        except ValueError:
            raise ValueError(f"Invalid number in range '{range_str}'")

        # Validate range values
        if not (0 <= start_pct <= 100):
            raise ValueError(f"Value {start_pct} must be between 0 and 100")

        if not (0 <= end_pct <= 100):
            raise ValueError(f"Value {end_pct} must be between 0 and 100")

        # Auto-swap if reversed
        if start_pct > end_pct:
            start_pct, end_pct = end_pct, start_pct

        # Skip empty ranges
        if start_pct == end_pct:
            continue

        ranges.append((start_pct, end_pct))

    return ranges


def get_included_samples(data, excluded_regions_str):
    """
    Extract samples excluding specified regions.

    Args:
        data: 1D numpy array
        excluded_regions_str: String format like '11-90' (percent-based)

    Returns:
        Tuple of (included_data, excluded_ranges_indices) where:
        - included_data: concatenated array of included samples
        - excluded_ranges_indices: list of (start_idx, end_idx) tuples for excluded regions in data indices
    """
    n = len(data)
    if n == 0:
        return data, []

    # Parse excluded regions, catch errors and return full data if invalid
    try:
        excluded_ranges_pct = parse_excluded_regions(excluded_regions_str)
    except ValueError as e:
        print(f"Warning: Invalid excluded regions format: {e}")
        return data, []

    if not excluded_ranges_pct:
        return data, []

    # Convert percent to indices
    excluded_ranges_idx = []
    for start_pct, end_pct in excluded_ranges_pct:
        start_idx = int(n * start_pct / 100)
        end_idx = int(n * end_pct / 100)
        # Clamp to valid range
        start_idx = max(0, min(start_idx, n))
        end_idx = max(0, min(end_idx, n))
        if start_idx < end_idx:
            excluded_ranges_idx.append((start_idx, end_idx))

    # Create mask for included samples
    mask = np.ones(n, dtype=bool)
    for start_idx, end_idx in excluded_ranges_idx:
        mask[start_idx:end_idx] = False

    # Extract included samples
    included_data = data[mask]

    return included_data, excluded_ranges_idx
