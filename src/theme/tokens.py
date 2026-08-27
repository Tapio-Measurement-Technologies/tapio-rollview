# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Reads ``tokens.json`` and hands out the values for one theme.

Nothing else in the tree reads ``tokens.json`` directly, and nothing else in
the tree contains a hex colour. Widgets and charts ask for a *role*
(``t.color("accent")``) rather than a ramp step, which is what makes the dark
theme a one-line change rather than a rewrite.

Import-safe: no Qt, no Matplotlib. ``theme.qt`` and ``theme.mpl`` build on it.
"""

import json

from theme.paths import theme_file

LIGHT = "light"
DARK = "dark"
THEMES = (LIGHT, DARK)

# The four status states. There are only these four; a fifth "informational
# blue" state does not exist — that is what ordinary text is for.
STATUS_GOOD = "good"
STATUS_WARN = "warn"
STATUS_BAD = "bad"
STATUS_IDLE = "idle"

_TOKENS_PATH = theme_file("tokens.json")
_raw = None


def _document():
    global _raw
    if _raw is None:
        with open(_TOKENS_PATH, encoding="utf-8") as handle:
            _raw = json.load(handle)
    return _raw


def _strip_comments(mapping):
    return {key: value for key, value in mapping.items() if not key.startswith("$")}


def hex_to_rgb(value):
    """``"#1E73BE"`` -> ``(30, 115, 190)``."""
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgba(value, alpha):
    """A token hex plus an alpha, as the ``rgba(r, g, b, a)`` Qt style sheets want."""
    red, green, blue = hex_to_rgb(value)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def mix(foreground, background, weight):
    """``weight`` of *foreground* over *background*, as a hex.

    Only ever used to render a token at partial strength (a disabled label, a
    hairline). It cannot invent a hue, so it does not breach "never introduce a
    colour".
    """
    fore = hex_to_rgb(foreground)
    back = hex_to_rgb(background)
    blended = (round(f * weight + b * (1 - weight)) for f, b in zip(fore, back))
    return "#" + "".join(f"{channel:02X}" for channel in blended)


class Tokens:
    """The token table resolved for one theme."""

    def __init__(self, theme=LIGHT):
        if theme not in THEMES:
            theme = LIGHT

        document = _document()
        self.theme = theme
        self.version = document["version"]

        self._semantic = _strip_comments(document["semantic"][theme])
        self._chart = _strip_comments(document["chart"][theme])
        self._palettes = document["palettes"]
        self._type = document["typography"]
        self._space = document["space"]
        self._radius = _strip_comments(document["radius"])
        self._motion = _strip_comments(document["motion"])
        self._elevation = _strip_comments(document["elevation"])
        self.metrics = _strip_comments(document["metrics"])
        self.ramps = document["ramps"]
        self.steps = document["steps"]

    # ---- colour -----------------------------------------------------------

    def color(self, role):
        """A semantic colour by role. Raises on an unknown role, deliberately."""
        try:
            return self._semantic[role]
        except KeyError:
            raise KeyError(
                f"'{role}' is not a Tapio semantic token. "
                f"Known roles: {', '.join(sorted(self._semantic))}"
            ) from None

    def ramp(self, name, step):
        """A raw ramp step. Only the theme package itself should need this."""
        return self.ramps[name][self.steps.index(step)]

    def chart(self, role):
        """Chart chrome: surface, grid, axis, tick, limit, band, target."""
        return self._chart[role]

    @property
    def band_alpha(self):
        return self._chart["band-alpha"]

    # ---- chart palettes ---------------------------------------------------

    @property
    def series(self):
        """The eight categorical slots, in fixed order. Slot 1 is the brand blue."""
        return list(self._palettes["categorical"][self.theme])

    @property
    def series_names(self):
        return list(self._palettes["categorical"]["names"])

    def series_color(self, index):
        """Slot *index*, assigned in sequence and never cycled past eight.

        A ninth series does not get a ninth colour: it folds into "Other", or the
        chart becomes small multiples. Callers that cannot honour that get the
        last slot rather than a wrapped-around duplicate.
        """
        slots = self.series
        return slots[min(index, len(slots) - 1)]

    @property
    def scatter_series(self):
        return list(self._palettes["scatter_safe"][self.theme])

    @property
    def recency(self):
        """Steps for stacked profiles, newest first."""
        return list(self._palettes["recency"][self.theme])

    @property
    def sequential(self):
        return list(self._palettes["sequential"][self.theme])

    @property
    def diverging(self):
        return list(self._palettes["diverging"][self.theme])

    def status_color(self, state):
        return self._palettes["status"][self.theme][state]

    def status_ink(self, state):
        """Text colour for a status, which is not the same as its mark colour."""
        return {
            STATUS_GOOD: self.color("good"),
            STATUS_WARN: self.color("warn"),
            STATUS_BAD: self.color("bad"),
            STATUS_IDLE: self.color("ink-muted"),
        }[state]

    def status_soft(self, state):
        return {
            STATUS_GOOD: self.color("good-soft"),
            STATUS_WARN: self.color("warn-soft"),
            STATUS_BAD: self.color("bad-soft"),
            STATUS_IDLE: self.color("sunken"),
        }[state]

    def status_mark(self, state):
        return {
            STATUS_GOOD: self.color("good-mark"),
            STATUS_WARN: self.color("warn-mark"),
            STATUS_BAD: self.color("bad-mark"),
            STATUS_IDLE: self.color("border-strong"),
        }[state]

    # ---- type -------------------------------------------------------------

    @property
    def sans_stack(self):
        return list(self._type["sans"])

    @property
    def mono_stack(self):
        return list(self._type["mono"])

    def font(self, step):
        """One step of the type scale as a dict: size, line, weight, family."""
        return dict(self._type["scale"][step])

    def font_size(self, step):
        return self._type["scale"][step]["size"]

    # ---- metrics ----------------------------------------------------------

    def space(self, step):
        return self._space[str(step)]

    def radius(self, name):
        return self._radius[name]

    def motion(self, name):
        return self._motion[name]

    def elevation(self, name):
        return dict(self._elevation[name])

    @property
    def control_height(self):
        return self.metrics["control"]

    @property
    def row_height(self):
        return self.metrics["row"]

    @property
    def min_target(self):
        return self.metrics["min_target"]

    @property
    def base_text_size(self):
        return self.metrics["text"]


def load(theme=LIGHT):
    return Tokens(theme=theme)
