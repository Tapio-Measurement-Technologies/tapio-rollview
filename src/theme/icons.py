# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The Tapio icon set: outline, geometric, drawn on a 24 px grid.

1.5 px stroke, round caps and joins, no fills, rendered at 16 / 20 / 24 / 32 px.
Icons are stored as SVG path data and painted at request time in whatever token
colour the caller needs, so the same file serves both themes.

An icon never appears alone on a primary action — icon plus label, or label
only. Icon-only buttons are permitted in dense toolbars, and then a tooltip is
mandatory.
"""

import atexit
import os
import shutil
import tempfile

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from theme import tokens as T

_icon_tokens = T.load()

#: The icon spec, from the token file rather than re-typed here: a 24 px grid,
#: a 1.5 stroke, round caps and joins. The paths below are drawn on that grid.
#: The system's rendered sizes are 16/20/24/32 — the smaller glyphs baked into
#: the style sheet (a 12 px combo chevron, a 10 px sort arrow) are chrome inside
#: a control rather than icons in the set, and are sized to the control.
GRID = _icon_tokens.icon("grid")
STROKE = _icon_tokens.icon("stroke")
CAP = _icon_tokens.icon("cap")
JOIN = _icon_tokens.icon("join")

# Path data on a 24x24 viewBox. Verbs the measurement work actually uses, plus
# the four status marks and the small chrome glyphs the style sheet needs.
PATHS = {
    # measurement verbs
    "measure":  "M3 8h18v8H3z M7 8v3M11 8v5M15 8v3M19 8v5",
    "profile":  "M3 16l4-6 4 3 3-7 4 5 3-2",
    "spectrum": "M3 20V9M8 20V4M13 20v-8M18 20V7M22 20v-5",
    "limits":   "M3 7h18M3 17h18 M3 12h4l3 4 3-8 3 4h5",
    "export":   "M12 3v12M8 7l4-4 4 4 M4 15v4a1 1 0 001 1h14a1 1 0 001-1v-4",
    "device":   "M7 2h10a2 2 0 012 2v16a2 2 0 01-2 2H7a2 2 0 01-2-2V4a2 2 0 012-2z M11 18h2",
    "roll":     "M12 3a8 3 0 010 6 8 3 0 010-6 M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6",
    "scan":     "M11 4a7 7 0 100 14 7 7 0 000-14z M16 16l4 4",
    "folder":   "M3 7a1 1 0 011-1h5l2 2h9a1 1 0 011 1v9a1 1 0 01-1 1H4a1 1 0 01-1-1z",
    "settings": "M12 9a3 3 0 100 6 3 3 0 000-6z M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1v.3a2 2 0 11-4 0v-.2a1.6 1.6 0 00-2.8-1.1l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 004.6 15a2 2 0 00-1.8-1.2H2.5a2 2 0 110-4h.2A1.6 1.6 0 004.2 7l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3h.1A1.6 1.6 0 0010 3v-.3a2 2 0 114 0v.2a1.6 1.6 0 002.7 1.1l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8v.1a1.6 1.6 0 001.5 1h.3a2 2 0 110 4h-.2a1.6 1.6 0 00-1.4 1z",
    # status marks — each ships with the status colour and a text label
    "good":     "M4 12.5l5.5 5.5L20 7",
    "warn":     "M12 4l9 16H3z M12 10v4M12 17v.01",
    "bad":      "M12 3a9 9 0 100 18 9 9 0 000-18z M12 7v6M12 16.5v.01",
    "idle":     "M12 3a9 9 0 100 18 9 9 0 000-18z M12 7v5l3 2",
    # chrome
    "chevron-down": "M5 9l7 7 7-7",
    "chevron-up":   "M5 15l7-7 7 7",
    "check":        "M4 12.5l5.5 5.5L20 7",
    "close":        "M6 6l12 12M18 6L6 18",
    "plus":         "M12 5v14M5 12h14",
    "stop":         "M7 7h10v10H7z",
}

# Stroke widths per status mark, matching the guide's specimens: the check and
# the triangle need a touch more weight to read at 12 px.
_WEIGHTS = {"good": 2.6, "warn": 2.4, "bad": 2.4, "idle": 2.2, "check": 2.6}

_cache = {}
_icon_dir = None


#: Marks that are shapes rather than strokes. A stop square drawn as an
#: outline reads as a checkbox, and drawn as a heavy stroke it rounds into a
#: dot; it wants a fill.
FILLED = {"stop"}


def _svg(name, color, stroke=None):
    if name in FILLED:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" '
            f'width="{GRID}" height="{GRID}">'
            f'<path d="{PATHS[name]}" fill="{color}"/></svg>'
        ).encode("utf-8")

    width = stroke if stroke is not None else _WEIGHTS.get(name, STROKE)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" '
        f'width="{GRID}" height="{GRID}" fill="none">'
        f'<path d="{PATHS[name]}" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="{CAP}" stroke-linejoin="{JOIN}"/></svg>'
    ).encode("utf-8")


def pixmap(name, size, color, stroke=None, ratio=1.0):
    """Render one icon at *size* px in *color* (a token hex)."""
    key = (name, size, color, stroke, ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    target = QPixmap(int(size * ratio), int(size * ratio))
    target.setDevicePixelRatio(ratio)
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()

    _cache[key] = target
    return target


def icon(name, size, color, stroke=None):
    return QIcon(pixmap(name, size, color, stroke))


def write_png(name, size, color, stroke=None):
    """Write an icon to a PNG and return its path.

    Qt style sheets can only reference an image by URL, so the handful of
    glyphs the sheet needs — the combo chevron, the checkbox tick, the sort
    arrows — are baked to disk when a theme is applied.
    """
    global _icon_dir
    if _icon_dir is None:
        _icon_dir = tempfile.mkdtemp(prefix="tapio-theme-")
        # One directory per process, and nothing else knows it exists, so its
        # removal has to be booked here. Without this every launch left a
        # tapio-theme-* directory behind in the system temp folder, for the
        # lifetime of the machine.
        atexit.register(shutil.rmtree, _icon_dir, ignore_errors=True)

    path = os.path.join(
        _icon_dir, f"{name}-{size}-{color.lstrip('#')}-{stroke or 'd'}.png"
    )
    if not os.path.exists(path):
        pixmap(name, size, color, stroke).save(path, "PNG")
    # Qt style sheets take forward slashes on every platform.
    return path.replace(os.sep, "/")


def clear_cache():
    _cache.clear()
