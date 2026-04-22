from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, TypedDict

from utils.range_utils import NumericRange, normalize_numeric_range, ranges_to_visual_coordinates


AnnotationMode = Literal["relative", "absolute"]
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

ANNOTATION_MODE_RELATIVE: AnnotationMode = "relative"
ANNOTATION_MODE_ABSOLUTE: AnnotationMode = "absolute"


class HighlightedRegionDict(TypedDict):
    start: float
    end: float
    mode: AnnotationMode
    color: TableauColor


@dataclass(frozen=True)
class HighlightedRegion:
    start: float
    end: float
    mode: AnnotationMode
    color: TableauColor

    @property
    def numeric_range(self) -> NumericRange:
        return NumericRange(self.start, self.end)

    def normalized(self) -> HighlightedRegion | None:
        normalized_range = self.numeric_range.normalized()
        if normalized_range is None:
            return None
        return HighlightedRegion(
            start=normalized_range.start,
            end=normalized_range.end,
            mode=self.mode,
            color=self.color,
        )

    def to_dict(self) -> HighlightedRegionDict:
        return {
            "start": self.start,
            "end": self.end,
            "mode": self.mode,
            "color": self.color,
        }


@dataclass(frozen=True)
class VisualHighlightedRegion:
    start: float
    end: float
    color: TableauColor


def _is_valid_mode(value: Any) -> bool:
    return value in (ANNOTATION_MODE_RELATIVE, ANNOTATION_MODE_ABSOLUTE)


def _is_valid_color(value: Any) -> bool:
    return value in TABLEAU_COLORS


def create_highlighted_region(
    start: float,
    end: float,
    mode: AnnotationMode,
    color: TableauColor,
) -> HighlightedRegion | None:
    region = HighlightedRegion(start=float(start), end=float(end), mode=mode, color=color)
    return region.normalized()


def parse_highlighted_region(
    start_text: str,
    end_text: str,
    mode: AnnotationMode,
    color: TableauColor,
) -> HighlightedRegion | None:
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

    return HighlightedRegion(
        start=numeric_range.start,
        end=numeric_range.end,
        mode=mode,
        color=color,
    )


def serialize_highlighted_regions(regions: list[HighlightedRegion]) -> list[HighlightedRegionDict]:
    return [region.to_dict() for region in regions]


def normalize_highlighted_regions(value: Any) -> list[HighlightedRegion]:
    if not isinstance(value, list):
        return []

    normalized_regions: list[HighlightedRegion] = []
    for item in value:
        if isinstance(item, HighlightedRegion):
            region = item.normalized()
            if region is not None:
                normalized_regions.append(region)
            continue

        if not isinstance(item, dict):
            continue

        mode = item.get("mode")
        color = item.get("color")
        if not _is_valid_mode(mode) or not _is_valid_color(color):
            continue

        try:
            region = create_highlighted_region(
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


def get_visual_highlighted_regions(
    regions: list[HighlightedRegion],
    distances,
    absolute_scale: float = 1.0,
) -> list[VisualHighlightedRegion]:
    visual_regions: list[VisualHighlightedRegion] = []

    for mode in (ANNOTATION_MODE_RELATIVE, ANNOTATION_MODE_ABSOLUTE):
        matching_regions = [region for region in regions if region.mode == mode]
        if not matching_regions:
            continue

        numeric_ranges = [region.numeric_range for region in matching_regions]
        if mode == ANNOTATION_MODE_ABSOLUTE and absolute_scale != 1.0:
            numeric_ranges = [numeric_range.scaled(absolute_scale) for numeric_range in numeric_ranges]

        visual_ranges = ranges_to_visual_coordinates(numeric_ranges, mode, distances)
        for region, visual_range in zip(matching_regions, visual_ranges):
            visual_regions.append(
                VisualHighlightedRegion(
                    start=visual_range.start,
                    end=visual_range.end,
                    color=region.color,
                )
            )

    return visual_regions
