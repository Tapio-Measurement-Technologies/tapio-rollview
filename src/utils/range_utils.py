from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal

import numpy as np


RangeMode = Literal["none", "relative", "absolute"]

_RANGE_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*-\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


@dataclass(frozen=True)
class NumericRange:
    start: float
    end: float

    def normalized(self) -> NumericRange | None:
        start_value = float(self.start)
        end_value = float(self.end)
        if start_value > end_value:
            start_value, end_value = end_value, start_value
        if start_value == end_value:
            return None
        return NumericRange(start=start_value, end=end_value)

    def scaled(self, factor: float) -> NumericRange:
        if factor == 1.0:
            return self
        return NumericRange(self.start * factor, self.end * factor)

    def as_tuple(self) -> tuple[float, float]:
        return (self.start, self.end)


def clamp_value(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def normalize_numeric_range(start: float, end: float) -> NumericRange | None:
    return NumericRange(start, end).normalized()


def parse_numeric_range(range_str: str) -> NumericRange | None:
    match = _RANGE_RE.fullmatch(range_str.strip())
    if not match:
        raise ValueError(f"Invalid range format '{range_str}'. Expected format: 'start-end'")

    try:
        start_value = float(match.group(1))
        end_value = float(match.group(2))
    except ValueError:
        raise ValueError(f"Invalid number in range '{range_str}'")

    return normalize_numeric_range(start_value, end_value)


def parse_numeric_ranges(ranges_str: str) -> list[NumericRange]:
    if not ranges_str or not ranges_str.strip():
        return []

    ranges: list[NumericRange] = []
    for range_str in ranges_str.strip().split(","):
        cleaned = range_str.strip()
        if not cleaned:
            continue

        parsed = parse_numeric_range(cleaned)
        if parsed is not None:
            ranges.append(parsed)

    return ranges


def serialize_numeric_ranges(ranges: Iterable[NumericRange]) -> str:
    return ",".join(f"{numeric_range.start:g}-{numeric_range.end:g}" for numeric_range in ranges)


def scale_numeric_ranges(ranges: Iterable[NumericRange], factor: float) -> list[NumericRange]:
    if factor == 1.0:
        return list(ranges)
    return [numeric_range.scaled(factor) for numeric_range in ranges]


def relative_ranges_to_indices(sample_count: int, ranges: Iterable[NumericRange]) -> list[tuple[int, int]]:
    index_ranges: list[tuple[int, int]] = []
    for numeric_range in ranges:
        start_pct = clamp_value(numeric_range.start, 0.0, 100.0)
        end_pct = clamp_value(numeric_range.end, 0.0, 100.0)
        start_idx = int(sample_count * start_pct / 100.0)
        end_idx = int(sample_count * end_pct / 100.0)
        start_idx = max(0, min(start_idx, sample_count))
        end_idx = max(0, min(end_idx, sample_count))
        if start_idx < end_idx:
            index_ranges.append((start_idx, end_idx))
    return index_ranges


def absolute_ranges_to_indices(
    distances: Iterable[float] | np.ndarray | None,
    ranges: Iterable[NumericRange],
) -> list[tuple[int, int]]:
    if distances is None:
        return []

    distance_array = np.asarray(distances, dtype=float)
    if len(distance_array) == 0:
        return []

    profile_start = float(distance_array[0])
    profile_end = float(distance_array[-1])
    index_ranges: list[tuple[int, int]] = []

    for numeric_range in ranges:
        start_value = clamp_value(numeric_range.start, profile_start, profile_end)
        end_value = clamp_value(numeric_range.end, profile_start, profile_end)
        start_idx = int(np.searchsorted(distance_array, start_value, side="left"))
        end_idx = int(np.searchsorted(distance_array, end_value, side="right"))
        start_idx = max(0, min(start_idx, len(distance_array)))
        end_idx = max(0, min(end_idx, len(distance_array)))
        if start_idx < end_idx:
            index_ranges.append((start_idx, end_idx))

    return index_ranges


def ranges_to_visual_coordinates(
    ranges: Iterable[NumericRange],
    mode: RangeMode,
    distances: Iterable[float] | np.ndarray | None,
) -> list[NumericRange]:
    if distances is None:
        return []

    distance_array = np.asarray(distances, dtype=float)
    if len(distance_array) == 0 or mode == "none":
        return []

    profile_start = float(distance_array[0])
    profile_end = float(distance_array[-1])
    profile_span = profile_end - profile_start
    visual_ranges: list[NumericRange] = []

    for numeric_range in ranges:
        if mode == "absolute":
            start_value = clamp_value(numeric_range.start, profile_start, profile_end)
            end_value = clamp_value(numeric_range.end, profile_start, profile_end)
        else:
            start_pct = clamp_value(numeric_range.start, 0.0, 100.0)
            end_pct = clamp_value(numeric_range.end, 0.0, 100.0)
            start_value = profile_start + profile_span * start_pct / 100.0
            end_value = profile_start + profile_span * end_pct / 100.0

        visual_ranges.append(NumericRange(start=start_value, end=end_value))

    return visual_ranges
