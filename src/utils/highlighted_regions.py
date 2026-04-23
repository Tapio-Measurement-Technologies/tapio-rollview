from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, TypedDict

from utils.range_utils import NumericRange, normalize_numeric_range, ranges_to_visual_coordinates


DistanceHighlightMode = Literal["relative", "absolute"]
HardnessHighlightMode = Literal["fixed", "mean_offset_absolute", "mean_offset_relative"]
TableauColor = Literal[
    "tab:blue",
    "tab:orange",
    "tab:green",
    "tab:red",
    "tab:purple",
    "tab:brown",
    "tab:pink",
    "tab:gray",
    "tab:olive",
    "tab:cyan",
]

TABLEAU_COLORS: tuple[TableauColor, ...] = (
    "tab:blue",
    "tab:orange",
    "tab:green",
    "tab:red",
    "tab:purple",
    "tab:brown",
    "tab:pink",
    "tab:gray",
    "tab:olive",
    "tab:cyan",
)

DISTANCE_HIGHLIGHT_MODE_RELATIVE: DistanceHighlightMode = "relative"
DISTANCE_HIGHLIGHT_MODE_ABSOLUTE: DistanceHighlightMode = "absolute"

HARDNESS_HIGHLIGHT_MODE_FIXED: HardnessHighlightMode = "fixed"
HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE: HardnessHighlightMode = "mean_offset_absolute"
HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE: HardnessHighlightMode = "mean_offset_relative"


class DistanceHighlightRegionDict(TypedDict):
    start: float
    end: float
    mode: DistanceHighlightMode
    color: TableauColor


class FixedHardnessHighlightRegionDict(TypedDict):
    mode: Literal["fixed"]
    color: TableauColor
    min_value: float
    max_value: float


class AbsoluteMeanOffsetHardnessHighlightRegionDict(TypedDict, total=False):
    mode: Literal["mean_offset_absolute"]
    color: TableauColor
    below_offset: float
    above_offset: float


class RelativeMeanOffsetHardnessHighlightRegionDict(TypedDict, total=False):
    mode: Literal["mean_offset_relative"]
    color: TableauColor
    below_percent: float
    above_percent: float


HardnessHighlightRegionDict = (
    FixedHardnessHighlightRegionDict
    | AbsoluteMeanOffsetHardnessHighlightRegionDict
    | RelativeMeanOffsetHardnessHighlightRegionDict
)


@dataclass(frozen=True)
class DistanceHighlightRegion:
    start: float
    end: float
    mode: DistanceHighlightMode
    color: TableauColor

    @property
    def numeric_range(self) -> NumericRange:
        return NumericRange(self.start, self.end)

    def normalized(self) -> DistanceHighlightRegion | None:
        normalized_range = self.numeric_range.normalized()
        if normalized_range is None:
            return None
        return DistanceHighlightRegion(
            start=normalized_range.start,
            end=normalized_range.end,
            mode=self.mode,
            color=self.color,
        )

    def to_dict(self) -> DistanceHighlightRegionDict:
        return {
            "start": self.start,
            "end": self.end,
            "mode": self.mode,
            "color": self.color,
        }


@dataclass(frozen=True)
class FixedHardnessHighlightRegion:
    color: TableauColor
    min_value: float
    max_value: float
    mode: Literal["fixed"] = HARDNESS_HIGHLIGHT_MODE_FIXED

    def normalized(self) -> FixedHardnessHighlightRegion | None:
        numeric_range = normalize_numeric_range(float(self.min_value), float(self.max_value))
        if numeric_range is None:
            return None
        return FixedHardnessHighlightRegion(
            color=self.color,
            min_value=numeric_range.start,
            max_value=numeric_range.end,
        )

    def to_dict(self) -> FixedHardnessHighlightRegionDict:
        return {
            "mode": self.mode,
            "color": self.color,
            "min_value": self.min_value,
            "max_value": self.max_value,
        }


@dataclass(frozen=True)
class AbsoluteMeanOffsetHardnessHighlightRegion:
    color: TableauColor
    below_offset: float | None = None
    above_offset: float | None = None
    mode: Literal["mean_offset_absolute"] = HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE

    def normalized(self) -> AbsoluteMeanOffsetHardnessHighlightRegion | None:
        below_offset = _normalize_optional_non_negative(self.below_offset)
        above_offset = _normalize_optional_non_negative(self.above_offset)
        if below_offset is None and above_offset is None:
            return None
        return AbsoluteMeanOffsetHardnessHighlightRegion(
            color=self.color,
            below_offset=below_offset,
            above_offset=above_offset,
        )

    def to_dict(self) -> AbsoluteMeanOffsetHardnessHighlightRegionDict:
        payload: AbsoluteMeanOffsetHardnessHighlightRegionDict = {
            "mode": self.mode,
            "color": self.color,
        }
        if self.below_offset is not None:
            payload["below_offset"] = self.below_offset
        if self.above_offset is not None:
            payload["above_offset"] = self.above_offset
        return payload


@dataclass(frozen=True)
class RelativeMeanOffsetHardnessHighlightRegion:
    color: TableauColor
    below_percent: float | None = None
    above_percent: float | None = None
    mode: Literal["mean_offset_relative"] = HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE

    def normalized(self) -> RelativeMeanOffsetHardnessHighlightRegion | None:
        below_percent = _normalize_optional_non_negative(self.below_percent)
        above_percent = _normalize_optional_non_negative(self.above_percent)
        if below_percent is None and above_percent is None:
            return None
        return RelativeMeanOffsetHardnessHighlightRegion(
            color=self.color,
            below_percent=below_percent,
            above_percent=above_percent,
        )

    def to_dict(self) -> RelativeMeanOffsetHardnessHighlightRegionDict:
        payload: RelativeMeanOffsetHardnessHighlightRegionDict = {
            "mode": self.mode,
            "color": self.color,
        }
        if self.below_percent is not None:
            payload["below_percent"] = self.below_percent
        if self.above_percent is not None:
            payload["above_percent"] = self.above_percent
        return payload


HardnessHighlightRegion = (
    FixedHardnessHighlightRegion
    | AbsoluteMeanOffsetHardnessHighlightRegion
    | RelativeMeanOffsetHardnessHighlightRegion
)


@dataclass(frozen=True)
class VisualHighlightRegion:
    start: float
    end: float
    color: TableauColor


def _normalize_optional_non_negative(value: float | None) -> float | None:
    if value is None:
        return None
    normalized_value = float(value)
    if normalized_value < 0:
        raise ValueError("Highlight range values must be non-negative.")
    return normalized_value


def _is_valid_distance_mode(value: Any) -> bool:
    return value in (DISTANCE_HIGHLIGHT_MODE_RELATIVE, DISTANCE_HIGHLIGHT_MODE_ABSOLUTE)


def _is_valid_hardness_mode(value: Any) -> bool:
    return value in (
        HARDNESS_HIGHLIGHT_MODE_FIXED,
        HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE,
        HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE,
    )


def _is_valid_color(value: Any) -> bool:
    return value in TABLEAU_COLORS


def create_distance_highlight_region(
    start: float,
    end: float,
    mode: DistanceHighlightMode,
    color: TableauColor,
) -> DistanceHighlightRegion | None:
    region = DistanceHighlightRegion(start=float(start), end=float(end), mode=mode, color=color)
    return region.normalized()


def parse_distance_highlight_region(
    start_text: str,
    end_text: str,
    mode: DistanceHighlightMode,
    color: TableauColor,
) -> DistanceHighlightRegion | None:
    start_clean = start_text.strip()
    end_clean = end_text.strip()

    if not start_clean and not end_clean:
        return None

    try:
        start_value = float(start_clean) if start_clean else -math.inf
        end_value = float(end_clean) if end_clean else math.inf
    except ValueError as exc:
        raise ValueError("Invalid range format. Expected numeric start and end values.") from exc

    numeric_range = normalize_numeric_range(start_value, end_value)
    if numeric_range is None:
        return None

    return DistanceHighlightRegion(
        start=numeric_range.start,
        end=numeric_range.end,
        mode=mode,
        color=color,
    )


def parse_hardness_highlight_region(
    first_text: str,
    second_text: str,
    mode: HardnessHighlightMode,
    color: TableauColor,
) -> HardnessHighlightRegion | None:
    first_clean = first_text.strip()
    second_clean = second_text.strip()

    def parse_optional(value: str) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError("Invalid range format. Expected numeric values.") from exc

    first_value = parse_optional(first_clean)
    second_value = parse_optional(second_clean)

    try:
        if mode == HARDNESS_HIGHLIGHT_MODE_FIXED:
            if first_value is None and second_value is None:
                return None
            if first_value is None or second_value is None:
                return None
            return FixedHardnessHighlightRegion(
                color=color,
                min_value=first_value,
                max_value=second_value,
            ).normalized()

        if mode == HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE:
            return AbsoluteMeanOffsetHardnessHighlightRegion(
                color=color,
                below_offset=first_value,
                above_offset=second_value,
            ).normalized()

        return RelativeMeanOffsetHardnessHighlightRegion(
            color=color,
            below_percent=first_value,
            above_percent=second_value,
        ).normalized()
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def serialize_distance_highlight_regions(
    regions: list[DistanceHighlightRegion],
) -> list[DistanceHighlightRegionDict]:
    return [region.to_dict() for region in regions]


def serialize_hardness_highlight_regions(
    regions: list[HardnessHighlightRegion],
) -> list[HardnessHighlightRegionDict]:
    return [region.to_dict() for region in regions]


def normalize_distance_highlight_regions(value: Any) -> list[DistanceHighlightRegion]:
    if not isinstance(value, list):
        return []

    normalized_regions: list[DistanceHighlightRegion] = []
    for item in value:
        if isinstance(item, DistanceHighlightRegion):
            region = item.normalized()
            if region is not None:
                normalized_regions.append(region)
            continue

        if not isinstance(item, dict):
            continue

        mode = item.get("mode")
        color = item.get("color")
        if not _is_valid_distance_mode(mode) or not _is_valid_color(color):
            continue

        try:
            region = create_distance_highlight_region(
                start=float(item.get("start")),
                end=float(item.get("end")),
                mode=mode,
                color=color,
            )
        except (TypeError, ValueError):
            continue

        if region is not None:
            normalized_regions.append(region)

    return normalized_regions


def normalize_hardness_highlight_regions(value: Any) -> list[HardnessHighlightRegion]:
    if not isinstance(value, list):
        return []

    normalized_regions: list[HardnessHighlightRegion] = []
    concrete_types = (
        FixedHardnessHighlightRegion,
        AbsoluteMeanOffsetHardnessHighlightRegion,
        RelativeMeanOffsetHardnessHighlightRegion,
    )

    for item in value:
        if isinstance(item, concrete_types):
            try:
                region = item.normalized()
            except ValueError:
                continue
            if region is not None:
                normalized_regions.append(region)
            continue

        if not isinstance(item, dict):
            continue

        mode = item.get("mode")
        color = item.get("color")
        if not _is_valid_hardness_mode(mode) or not _is_valid_color(color):
            continue

        try:
            if mode == HARDNESS_HIGHLIGHT_MODE_FIXED:
                min_value = _coerce_required_float(item.get("min_value"))
                max_value = _coerce_required_float(item.get("max_value"))
                region = FixedHardnessHighlightRegion(color=color, min_value=min_value, max_value=max_value).normalized()
            elif mode == HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE:
                region = AbsoluteMeanOffsetHardnessHighlightRegion(
                    color=color,
                    below_offset=_coerce_optional_float(item.get("below_offset")),
                    above_offset=_coerce_optional_float(item.get("above_offset")),
                ).normalized()
            else:
                region = RelativeMeanOffsetHardnessHighlightRegion(
                    color=color,
                    below_percent=_coerce_optional_float(item.get("below_percent")),
                    above_percent=_coerce_optional_float(item.get("above_percent")),
                ).normalized()
        except (TypeError, ValueError):
            continue

        if region is not None:
            normalized_regions.append(region)

    return normalized_regions


def _coerce_required_float(value: Any) -> float:
    return float(value)


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_visual_distance_highlight_regions(
    regions: list[DistanceHighlightRegion],
    distances,
    absolute_scale: float = 1.0,
) -> list[VisualHighlightRegion]:
    visual_regions: list[VisualHighlightRegion] = []

    for mode in (DISTANCE_HIGHLIGHT_MODE_RELATIVE, DISTANCE_HIGHLIGHT_MODE_ABSOLUTE):
        matching_regions = [region for region in regions if region.mode == mode]
        if not matching_regions:
            continue

        numeric_ranges = [region.numeric_range for region in matching_regions]
        if mode == DISTANCE_HIGHLIGHT_MODE_ABSOLUTE and absolute_scale != 1.0:
            numeric_ranges = [numeric_range.scaled(absolute_scale) for numeric_range in numeric_ranges]

        visual_ranges = ranges_to_visual_coordinates(numeric_ranges, mode, distances)
        for region, visual_range in zip(matching_regions, visual_ranges):
            visual_regions.append(
                VisualHighlightRegion(
                    start=visual_range.start,
                    end=visual_range.end,
                    color=region.color,
                )
            )

    return visual_regions


def get_visual_hardness_highlight_regions(
    regions: list[HardnessHighlightRegion],
    mean_value: float | None,
) -> list[VisualHighlightRegion]:
    if mean_value is None or not math.isfinite(mean_value):
        return []

    visual_regions: list[VisualHighlightRegion] = []
    mean_magnitude = abs(mean_value)

    for region in regions:
        if isinstance(region, FixedHardnessHighlightRegion):
            lower = region.min_value
            upper = region.max_value
        elif isinstance(region, AbsoluteMeanOffsetHardnessHighlightRegion):
            lower = mean_value - region.below_offset if region.below_offset is not None else mean_value
            upper = mean_value + region.above_offset if region.above_offset is not None else mean_value
        else:
            lower = mean_value - mean_magnitude * region.below_percent / 100.0 if region.below_percent is not None else mean_value
            upper = mean_value + mean_magnitude * region.above_percent / 100.0 if region.above_percent is not None else mean_value

        numeric_range = normalize_numeric_range(lower, upper)
        if numeric_range is None:
            continue

        visual_regions.append(
            VisualHighlightRegion(
                start=numeric_range.start,
                end=numeric_range.end,
                color=region.color,
            )
        )

    return visual_regions
