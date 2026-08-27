# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Tapio Design System v1.0, as RollView implements it.

``tokens.json`` is the source of truth. The Qt palette, the style sheet and the
Matplotlib rcParams are all generated from it, so changing a token changes the
whole application and a hand-written hex anywhere else is a bug.

    import theme

    theme.apply(app, theme="light")

Submodules:

``theme.tokens``    the token table, resolved per theme (no Qt)
``theme.qt``        Fusion, fonts, palette, style sheet, property helpers
``theme.mpl``       chart tokens, ``profile()``, colormaps
``theme.widgets``   status pill, stat tile, application header
``theme.icons``     the 24 px outline icon set
``theme.contrast``  the WCAG audit that runs in the test suite
"""

from theme import tokens
from theme.tokens import (
    CHOICES,
    DARK,
    LIGHT,
    SYSTEM,
    STATUS_BAD,
    STATUS_GOOD,
    STATUS_IDLE,
    STATUS_WARN,
    THEMES,
)

VERSION = "1.0"


def apply(app=None, theme=LIGHT):
    """Apply the system to a Qt application *and* to Matplotlib.

    One call, because a chart drawn in the light palette inside a dark window
    is the failure mode this is meant to prevent.

    *theme* is ``light``, ``dark`` or ``system``; the last asks the desktop.
    Returns the tokens actually resolved, which are always one of the two.
    """
    from theme import mpl, qt

    resolved = qt.apply(app, theme=theme)
    # The *resolved* theme, not the requested one: "system" is not a table.
    mpl.use(resolved.theme)
    return resolved


def current():
    """The live token table."""
    from theme import qt

    return qt.current


def requested():
    """The theme as it was asked for, which may be ``system``.

    Use this, not ``current().theme``, to decide whether a change of desktop
    appearance should be followed.
    """
    from theme import qt

    return qt.requested


__all__ = [
    "VERSION", "apply", "current", "requested", "tokens",
    "LIGHT", "DARK", "SYSTEM", "THEMES", "CHOICES",
    "STATUS_GOOD", "STATUS_WARN", "STATUS_BAD", "STATUS_IDLE",
]
