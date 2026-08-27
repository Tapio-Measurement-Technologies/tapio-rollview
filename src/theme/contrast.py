# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""WCAG 2.2 contrast audit over the token table.

Contrast is verified with a script, not with eyes. Every pairing the interface
actually renders is enumerated here and checked in both themes; if a token
changes and a pair drops below its threshold, ``src/test/test_theme_tokens.py``
fails and the build says so.

Text needs 4.5:1. UI marks — focus rings, status marks, chart series against the
plot surface — need 3:1.
"""

from theme import tokens as T

TEXT_RATIO = 4.5
MARK_RATIO = 3.0


def _linear(channel):
    channel = channel / 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(hex_color):
    red, green, blue = T.hex_to_rgb(hex_color)
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def ratio(foreground, background):
    """WCAG contrast ratio between two hex colours, 1.0–21.0."""
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# Every surface a foreground can land on, and what may land on it. This is the
# list the interface actually renders, not every pairing the palette permits.
#
# `accent` is deliberately absent from the text list: it is a fill and a mark
# (button backgrounds, the tab underline, the focus ring), and prose in accent
# blue is not a pattern the system has. Links use the darker `link` token.
# Hairlines — `border`, `border-strong`, the chart axis and gridlines — are not
# marks either: they carry no state and no information, so WCAG 1.4.11 does not
# reach them and holding them to 3:1 would only make the interface louder.
_SURFACES = ("bg", "surface", "sunken", "raised")
_TEXT_ON_SURFACE = ("ink", "ink-secondary", "ink-muted", "link")
_STATUS_INKS = ("good", "warn", "bad")
_MARKS_ON_SURFACE = ("focus", "accent", "good-mark", "warn-mark", "bad-mark")


def pairs(theme):
    """Yield ``(kind, label, foreground, background, threshold)`` for one theme."""
    t = T.load(theme=theme)

    for surface in _SURFACES:
        background = t.color(surface)
        for ink in _TEXT_ON_SURFACE:
            yield ("text", f"{ink} on {surface}", t.color(ink), background, TEXT_RATIO)

    # A status word sits either on its own soft wash (the pill, the failing row)
    # or straight on a panel (the failing stat value).
    for ink in _STATUS_INKS:
        yield ("text", f"{ink} on {ink}-soft", t.color(ink), t.color(f"{ink}-soft"), TEXT_RATIO)
        for surface in ("surface", "sunken"):
            yield ("text", f"{ink} on {surface}", t.color(ink), t.color(surface), TEXT_RATIO)

    # Marks only have to clear 3:1, and only against the surfaces they sit on.
    for surface in ("surface", "sunken"):
        background = t.color(surface)
        for mark in _MARKS_ON_SURFACE:
            yield ("mark", f"{mark} on {surface}", t.color(mark), background, MARK_RATIO)

    # Every chart series against the plot surface, plus the limit and target marks.
    plot = t.chart("surface")
    for name, color in zip(t.series_names, t.series):
        yield ("mark", f"series {name} on plot", color, plot, MARK_RATIO)
    for role in ("limit", "target"):
        yield ("mark", f"chart {role} on plot", t.chart(role), plot, MARK_RATIO)

    # The alarm band. White on red-600 is 3.93:1, below the 4.5:1 a 13 px label
    # normally needs, and it is here because the guide pins the band to red-600
    # with white text — a colour chosen to read as a failure from two metres
    # away rather than to clear a ratio at reading distance. It is listed as a
    # mark rather than dropped, so the number stays visible and the pair cannot
    # quietly get worse. Raising it means darkening the band to red-800, which
    # is a design-system decision.
    yield ("mark", "white on the alarm band", "#FFFFFF", t.ramp("red", 600), MARK_RATIO)

    # Button labels against their own fill. A disabled control still has to be
    # legible, and every variant shares one disabled look: ink-muted on sunken.
    yield ("text", "accent-ink on accent", t.color("accent-ink"), t.color("accent"), TEXT_RATIO)
    yield ("text", "ink-inverse on inverse", t.color("ink-inverse"), t.color("inverse"), TEXT_RATIO)
    yield ("text", "disabled label on sunken", t.color("ink-muted"), t.color("sunken"), TEXT_RATIO)


def audit(theme=None):
    """Return ``(passes, failures)``; each failure is (label, ratio, threshold)."""
    themes = T.THEMES if theme is None else (theme,)
    passes = 0
    failures = []
    for name in themes:
        for kind, label, foreground, background, threshold in pairs(name):
            measured = ratio(foreground, background)
            if measured + 1e-9 < threshold:
                failures.append((f"{name}: {label}", round(measured, 2), threshold))
            else:
                passes += 1
    return passes, failures


def report():
    """Human-readable audit, for running by hand: ``python -m theme.contrast``."""
    lines = []
    for name in T.THEMES:
        checked = list(pairs(name))
        worst_text = min(
            (ratio(f, b) for kind, _, f, b, _ in checked if kind == "text"), default=0
        )
        worst_mark = min(
            (ratio(f, b) for kind, _, f, b, _ in checked if kind == "mark"), default=0
        )
        lines.append(
            f"{name:>5}: {len(checked)} pairs, "
            f"lowest text {worst_text:.2f}:1, lowest mark {worst_mark:.2f}:1"
        )
    passes, failures = audit()
    lines.append(f"{passes} pass, {len(failures)} fail")
    for label, measured, threshold in failures:
        lines.append(f"  FAIL {label}: {measured}:1 < {threshold}:1")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(report())
    sys.exit(1 if audit()[1] else 0)
