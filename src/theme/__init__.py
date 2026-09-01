# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The Tapio Design System, as RollView consumes it.

``tapio-tokens.json`` is the design system's own token file, carried here
unmodified; ``rollview-tokens.json`` beside it holds what RollView adds and
nothing else. The Qt palette, the style sheet and the Matplotlib rcParams are
all generated from the pair, so changing a token changes the whole application
and a hand-written hex anywhere else is a bug.

    import theme

    theme.apply(app, theme="light")

RollView carries its own Qt theme rather than the system's ``tapio_qt.py``,
because it needs several things that file does not do: registering the bundled
Plex faces, a proxy style for the behaviours a style sheet cannot reach, the
property helpers that re-polish, and a stylesheet that covers the widgets an
analysis tool actually uses. What it must not do is *diverge*: the tokens are
the system's, the role names are the system's, the component rules are the
guide's, and ``test_theme_tokens.py`` fails if any of the three drifts.

Nothing here reads the design system itself; the copy is what ships and what the
tests check. To take a new version of it::

    python scripts/sync_design_system.py --design-system /path/to/design-system

Submodules:

``theme.tokens``    the token table, resolved per theme and density (no Qt)
``theme.qt``        Fusion, fonts, palette, style sheet, property helpers
``theme.mpl``       chart tokens, ``profile()``, colormaps
``theme.widgets``   status pill, stat tile, application header
``theme.icons``     the 24 px outline icon set
``theme.contrast``  the WCAG audit that runs in the test suite
"""

from theme import tokens
from theme.tokens import (
    CHOICES,
    COMFORTABLE,
    COMPACT,
    DARK,
    DENSITIES,
    FIELD,
    LIGHT,
    SYSTEM,
    STATUS_BAD,
    STATUS_GOOD,
    STATUS_IDLE,
    STATUS_WARN,
    THEMES,
)

#: The version of the design system this build carries. Read from the token
#: file rather than restated, so it cannot claim one version and ship another.
VERSION = tokens.upstream()["version"]


def apply(app=None, theme=LIGHT, density=None):
    """Apply the system to a Qt application *and* to Matplotlib.

    One call, because a chart drawn in the light palette inside a dark window
    is the failure mode this is meant to prevent.

    *theme* is ``light``, ``dark`` or ``system``; the last asks the desktop.
    *density* is ``compact``, ``comfortable`` or ``field``, and defaults to the
    row RollView ships in. Returns the tokens actually resolved, which are
    always one of the two themes.
    """
    from theme import mpl, qt

    resolved = qt.apply(app, theme=theme, density=density)
    # The *resolved* theme, not the requested one: "system" is not a table.
    mpl.use(resolved.theme, density=resolved.density)
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
    "COMPACT", "COMFORTABLE", "FIELD", "DENSITIES",
    "STATUS_GOOD", "STATUS_WARN", "STATUS_BAD", "STATUS_IDLE",
]
