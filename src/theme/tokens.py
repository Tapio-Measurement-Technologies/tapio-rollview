# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Reads the design system's token file and hands out one theme's values.

``tapio-tokens.json`` is the Tapio Design System's own token file, copied in
without a byte changed. ``rollview-tokens.json`` beside it carries what RollView
adds and nothing more. Neither is edited by hand: ``scripts/sync_design_system.py``
re-copies the first and records its hash in the second, so a token that moves
upstream arrives here as a failing test rather than as a colour that quietly
disagrees with Tapio Analysis.

Nothing else in the tree reads either file, and nothing else in the tree
contains a hex colour. Widgets and charts ask for a *role* (``t.color("accent")``)
rather than a ramp step, which is what makes the dark theme a one-line change
rather than a rewrite.

Two vocabularies meet here and they are not the same thing:

* **Roles** are the system's semantic token names, spelled exactly as
  ``tokens.json`` spells them — ``surface-sunken``, ``ink-link``, ``danger``.
  RollView used to carry its own shorter spellings, which meant a rule written
  in the guide's words had to be translated before it could be applied. It no
  longer does.
* **States** are the four component states from the guide's status
  section — ``good``, ``warn``, ``bad``, ``idle``. They are what a widget *is*,
  not what colour it takes, and the guide's own QSS and CSS spell them this way
  (``QLabel[state="bad"]``). ``status_ink()`` and friends map a state onto the
  roles that paint it.

Anything the system already authors is read, never restated. Anything derivable
from what it authors is derived here: the status palette, the scatter-safe trio,
the recency ramp and the dark sequential ramp all fall out of tokens the system
does author, and deriving them is what keeps them right when it changes them.

Import-safe: no Qt, no Matplotlib. ``theme.qt`` and ``theme.mpl`` build on it.
"""

import json
import re

from theme.paths import theme_file

LIGHT = "light"
DARK = "dark"
#: The two token tables that exist. Everything downstream resolves to one.
THEMES = (LIGHT, DARK)

#: "Follow the desktop." Not a table — there are no system tokens to load — but
#: a valid answer to "which theme?", resolved against the platform by
#: ``theme.qt.resolve()`` at the moment a theme is applied.
SYSTEM = "system"
#: What a user may choose, in the order the settings page offers them.
CHOICES = (SYSTEM, LIGHT, DARK)

# The four status states. There are only these four; a fifth "informational
# blue" state does not exist — that is what ordinary text is for.
STATUS_GOOD = "good"
STATUS_WARN = "warn"
STATUS_BAD = "bad"
STATUS_IDLE = "idle"

#: The density rows the system defines. RollView runs the first of them and
#: carries the rest so a mill-floor or handheld build is a parameter rather than
#: a re-measurement. The system's sixth principle is "same system, different
#: density"; a token set with one row in it cannot keep that promise.
COMPACT = "compact"
COMFORTABLE = "comfortable"
FIELD = "field"
DENSITIES = (COMPACT, COMFORTABLE, FIELD)

#: Which column of the system's mark table a chart draws with.
SCREEN = "screen"
EXPORT = "export"
PRESETS = (SCREEN, EXPORT)

_SYSTEM_PATH = theme_file("tapio-tokens.json")
_ROLLVIEW_PATH = theme_file("rollview-tokens.json")

_system = None
_rollview = None


def _documents():
    global _system, _rollview
    if _system is None:
        with open(_SYSTEM_PATH, encoding="utf-8") as handle:
            _system = json.load(handle)
        with open(_ROLLVIEW_PATH, encoding="utf-8") as handle:
            _rollview = json.load(handle)
    return _system, _rollview


def system_document():
    """The design system's token file, as read. For the sync check and tests."""
    return _documents()[0]


def rollview_document():
    """RollView's additions, as read."""
    return _documents()[1]


def upstream():
    """Which version of the system this build carries, and its hash."""
    return dict(rollview_document()["$upstream"])


def _strip_comments(mapping):
    return {key: value for key, value in mapping.items() if not key.startswith("$")}


def hex_to_rgb(value):
    """``"#1E73BE"`` -> ``(30, 115, 190)``."""
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(channels):
    return "#" + "".join(f"{round(channel):02X}" for channel in channels)


def rgba(value, alpha):
    """A token hex plus an alpha, as the ``rgba(r, g, b, a)`` Qt style sheets want."""
    red, green, blue = hex_to_rgb(value)
    return f"rgba({red}, {green}, {blue}, {alpha})"


_CSS_RGBA = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)"
)


def parse_rgba(value):
    """``"rgba(239,71,44,0.08)"`` -> ``("#EF472C", 0.08)``.

    The system authors a translucent token as one CSS colour, because CSS, QSS
    and the guide all take it that way. Splitting it into a hex and an alpha at
    the point of use — rather than authoring the two halves separately — is what
    keeps it comparable with the file it came from.
    """
    match = _CSS_RGBA.match(value.strip())
    if not match:
        raise ValueError(f"{value!r} is not a CSS rgba() colour")
    red, green, blue, alpha = match.groups()
    return rgb_to_hex((int(red), int(green), int(blue))), float(alpha or 1.0)


def mix(foreground, background, weight):
    """``weight`` of *foreground* over *background*, as a hex.

    Only ever used to render a token at partial strength (a disabled label, a
    hairline). It cannot invent a hue, so it does not breach "never introduce a
    colour".
    """
    fore = hex_to_rgb(foreground)
    back = hex_to_rgb(background)
    return rgb_to_hex(f * weight + b * (1 - weight) for f, b in zip(fore, back))


class Tokens:
    """The token table resolved for one theme and one density."""

    def __init__(self, theme=LIGHT, density=None, preset=None):
        if theme not in THEMES:
            theme = LIGHT

        system, rollview = _documents()
        self.theme = theme
        self.version = system["$meta"]["version"]

        self._semantic = _strip_comments(system["semantic"][theme])
        self._chart = _strip_comments(system["chart"]["chrome"][theme])
        self._categorical = system["chart"]["categorical"]
        self._sequential = system["chart"]["sequential"]
        self._diverging = system["chart"]["diverging"]
        self._mark = system["chart"]["mark"]
        self._spectral = system["chart"]["spectral"]
        self._export = system["chart"]["export"]
        self._type = system["type"]
        self._space = system["space"]["scale"]
        self._radius = system["radius"]
        self._border = system["border"]
        self._motion = system["motion"]
        self._elevation = system["elevation"]
        self._size = system["size"]
        self._icon = system["icon"]
        self.ramps = system["ramp"]

        self._fallback = rollview["type"]["fallback"]
        self._supporting_mark = rollview["chart"]["supportingMark"]
        self._density_extra = _strip_comments(rollview["density"])

        self.density = density if density in DENSITIES else self._density_extra["default"]
        self.preset = preset if preset in PRESETS else rollview["chart"]["preset"]

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

    @property
    def roles(self):
        """Every semantic role the system defines, in file order."""
        return list(self._semantic)

    def ramp(self, name, step):
        """A raw ramp step. Only the theme package itself should need this."""
        return self.ramps[name][str(step)]

    def ramp_steps(self, name):
        """One ramp as a list, light to dark."""
        return [self.ramps[name][step] for step in sorted(self.ramps[name], key=int)]

    def chart(self, role):
        """Chart chrome: surface, grid, axis, tick, label, title, limit, target.

        ``label`` and ``title`` are the axis-label and title inks. They are not
        the same as ``ink-muted`` and ``ink``, and a chart that borrows the
        interface's inks for them is a chart drawn to a different spec than the
        one the guide states.
        """
        return self._chart[role]

    @property
    def limit_band(self):
        """The wash beyond a limit, as ``(hex, alpha)``."""
        return parse_rgba(self._chart["limit-band"])

    # ---- chart palettes ---------------------------------------------------

    @property
    def series(self):
        """The eight categorical slots, in fixed order. Slot 1 is the brand blue."""
        return list(self._categorical[self.theme])

    @property
    def series_names(self):
        return list(self._categorical["order"])

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
        """The all-pairs trio.

        Any two marks can end up adjacent in a scatter, so every pair has to
        separate — not just neighbours. Under that test the palette caps at
        three, and the system names which three.
        """
        return list(self._categorical["allPairsTrio"][self.theme])

    @property
    def sequential(self):
        """One hue, light to dark.

        The system authors the ramp once, in light-to-dark order. Dark mode
        reverses it so low magnitude sits nearest the surface — a derivation,
        not a second ramp to keep in step with the first.
        """
        steps = list(self._sequential["light"])
        return steps if self.theme == LIGHT else steps[::-1]

    @property
    def recency(self):
        """Steps for stacked profiles, newest first.

        Recency is an order, so it comes off the ordinal ramp rather than out of
        eight categorical hues. The system says where that ramp stops —
        ``ordinalLightEnd`` / ``ordinalDarkEnd``, the last step that still clears
        2:1 against the surface — and the walk starts one step off the accent so
        a stacked profile is never mistakeable for the mean drawn over it.
        """
        steps = list(self._sequential["light"])
        upper = [value.upper() for value in steps]
        start = upper.index(self.color("accent").upper())
        end = upper.index(
            self._sequential[
                "ordinalLightEnd" if self.theme == LIGHT else "ordinalDarkEnd"
            ].upper()
        )
        stride = 1 if end > start else -1
        return [steps[i] for i in range(start + stride, end + stride, stride)]

    @property
    def diverging(self):
        """Blue to gold with a neutral midpoint, in the order the system lists it.

        Which end is positive is a question for whoever builds the colormap —
        ``theme.mpl.diverging_cmap`` puts blue at the positive pole, because the
        guide says blue is positive and red is reserved.
        """
        return list(self._diverging[self.theme])

    def status_color(self, state):
        """The mark colour for a state: the fill, the dot, the pill's icon.

        Derived from the semantic roles rather than listed again. The system has
        no ``good-mark``: in spec is one colour, and both the guide's status row
        and ``tapio.css`` give the mark and the ink the same value.
        """
        return {
            STATUS_GOOD: self.color("good"),
            STATUS_WARN: self.color("warning-mark"),
            STATUS_BAD: self.color("danger-mark"),
            STATUS_IDLE: self.color("ink-muted"),
        }[state]

    def status_ink(self, state):
        """Text colour for a status, which is not the same as its mark colour."""
        return {
            STATUS_GOOD: self.color("good"),
            STATUS_WARN: self.color("warning"),
            STATUS_BAD: self.color("danger"),
            STATUS_IDLE: self.color("ink-muted"),
        }[state]

    def status_soft(self, state):
        return {
            STATUS_GOOD: self.color("good-soft"),
            STATUS_WARN: self.color("warning-soft"),
            STATUS_BAD: self.color("danger-soft"),
            STATUS_IDLE: self.color("surface-sunken"),
        }[state]

    def status_mark(self, state):
        """The mark for a state, on a surface rather than in a chart."""
        return {
            STATUS_GOOD: self.color("good"),
            STATUS_WARN: self.color("warning-mark"),
            STATUS_BAD: self.color("danger-mark"),
            STATUS_IDLE: self.color("border-strong"),
        }[state]

    # ---- chart marks ------------------------------------------------------

    def mark(self, name, preset=None):
        """One mark weight, in points.

        Points, not pixels: the same "2 px" line is a different physical
        thickness on a HiDPI laptop, in a screenshot, in a 300 dpi print and in
        a PDF. Every plotting library accepts points.
        """
        return self._mark[preset or self.preset][name]

    @property
    def supporting_mark(self):
        """The weight of an individual profile behind a mean, in points.

        RollView's own, because the system does not specify a chart of a mean
        over its members. It sits below the series weight without reaching the
        limit line's or the target's, neither of which is a data line.
        """
        return self._supporting_mark[self.preset]

    def dash(self, name):
        """A dash pattern, as the system authors it."""
        return list(self._mark["dash"][name])

    @property
    def spectral(self):
        """What a spectrum's axes are allowed to claim."""
        return dict(self._spectral)

    @property
    def raster_min_dpi(self):
        return self._export["rasterMinDpi"]

    @property
    def vector_formats(self):
        return list(self._export["vectorFormats"])

    # ---- type -------------------------------------------------------------

    @property
    def sans_stack(self):
        """The system's sans family, then what to fall back to without it."""
        return [self._type["family"]["sans"]] + list(self._fallback["sans"])

    @property
    def mono_stack(self):
        return [self._type["family"]["mono"]] + list(self._fallback["mono"])

    def font(self, step):
        """One step of the type scale: size, line, weight, family, and the rest.

        ``family`` is always present and is ``sans`` unless the step names
        another; the system leaves it out for the sans steps rather than
        repeating it eleven times.
        """
        spec = dict(self._type["scale"][step])
        spec.setdefault("family", "sans")
        spec["uppercase"] = spec.get("transform") == "uppercase"
        spec["tabular"] = spec.get("numeric") == "tabular-nums"
        return spec

    def font_size(self, step):
        return self._type["scale"][step]["size"]

    # ---- metrics ----------------------------------------------------------

    def space(self, step):
        return self._space[str(step)]

    def radius(self, name):
        return self._radius[name]

    def border(self, name):
        return self._border[name]

    def motion(self, name):
        """A duration in milliseconds, or an easing curve as authored."""
        value = self._motion[name]
        if isinstance(value, str) and value.endswith("ms"):
            return int(value[:-2])
        return value

    def elevation(self, name):
        return self._elevation[name]

    def icon(self, name):
        return self._icon[name]

    @property
    def densities(self):
        """Every density row, whole: row, pad, control, min target, base text."""
        rows = {}
        for name in DENSITIES:
            upstream_row = self._size["density"][name]
            rows[name] = {
                "row": upstream_row["row"],
                "pad": upstream_row["pad"],
                "control": self._density_extra["control"][name],
                "text": self._density_extra["text"][name],
                "min_target": self._size[f"target-{self._density_extra['target'][name]}"],
            }
        return rows

    @property
    def metrics(self):
        """The density row in force."""
        return self.densities[self.density]

    def target(self, kind):
        """A minimum hit target: ``pointer``, ``touch`` or ``gloved``."""
        return self._size[f"target-{kind}"]

    @property
    def control_height(self):
        return self.metrics["control"]

    @property
    def row_height(self):
        return self.metrics["row"]

    @property
    def cell_pad(self):
        return self.metrics["pad"]

    @property
    def min_target(self):
        return self.metrics["min_target"]

    @property
    def base_text_size(self):
        return self.metrics["text"]


def load(theme=LIGHT, density=None, preset=None):
    return Tokens(theme=theme, density=density, preset=preset)
