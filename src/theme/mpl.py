# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Tapio chart tokens for Matplotlib.

RollView's charts are not dashboard widgets. They are instruments: an operator
reads a value off one, decides whether a roll ships, and hands the plot to a
mill engineer. This module carries the rules from the design system so no chart
has to remember them:

* ``use(theme)`` swaps every chart token, ``tab10``-on-white included.
* ``profile()`` draws the curve, the limit lines, the washes beyond them, the
  out-of-spec segments redrawn on top, and the labelled extreme.
* ``sequential_cmap()`` / ``diverging_cmap()`` for magnitude and polarity.

Two rules are never bent: never a second y-axis, and never colour by value.
Colour carries identity — which channel this is. A profile that turns red where
it exceeds a limit is *status*, and that is the one exception.
"""

import os
import warnings

import matplotlib as mpl
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.font_manager import fontManager
from matplotlib.patches import Rectangle

from theme import tokens as T

# Mark specifications, from the design system.
PROFILE_WIDTH = 2.0        # profile lines, round joins and caps
VIOLATION_WIDTH = 2.6      # out-of-spec segments, redrawn on top
LIMIT_WIDTH = 1.5          # limit lines, solid
TARGET_WIDTH = 1.0         # target and mean, dashed and recessive
SUPPORTING_WIDTH = 1.5     # individual profiles behind the mean
EXTREME_MARKER = 8         # markers are >= 8 px and used selectively

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "plex"
)

current = T.load()
_fonts_registered = False


def _register_fonts():
    """Teach Matplotlib about the bundled Plex faces."""
    global _fonts_registered
    if _fonts_registered or not os.path.isdir(_FONT_DIR):
        _fonts_registered = True
        return
    for filename in sorted(os.listdir(_FONT_DIR)):
        if filename.endswith(".ttf"):
            try:
                fontManager.addfont(os.path.join(_FONT_DIR, filename))
            except (OSError, RuntimeError):
                pass
    _fonts_registered = True


def _families(stack):
    """Matplotlib wants family names, and silently ignores ones it cannot find."""
    known = {font.name for font in fontManager.ttflist}
    return [name for name in stack if name in known] or [stack[-1]]


def use(theme=T.LIGHT):
    """Point every chart at one theme's tokens. Returns the resolved tokens."""
    global current
    _register_fonts()
    current = T.load(theme=theme)
    t = current

    sans = _families(t.sans_stack)
    mono = _families(t.mono_stack)

    mpl.rcParams.update({
        "figure.facecolor": t.color("surface"),
        "figure.edgecolor": t.color("surface"),
        "figure.titlesize": t.font_size("title-3"),
        "figure.titleweight": "semibold",
        "savefig.facecolor": t.color("surface"),
        "savefig.edgecolor": t.color("surface"),
        "savefig.dpi": 200,

        "axes.facecolor": t.chart("surface"),
        "axes.edgecolor": t.chart("axis"),
        "axes.linewidth": 1.0,
        "axes.labelcolor": t.color("ink-muted"),
        "axes.labelsize": t.font_size("body-sm"),
        "axes.titlesize": t.font_size("body"),
        "axes.titlecolor": t.color("ink"),
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.prop_cycle": mpl.cycler(color=t.series),
        # Gridlines are hairlines, horizontal only for profiles. The top and
        # right spines are chrome competing with the data.
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,

        "grid.color": t.chart("grid"),
        "grid.linewidth": 1.0,
        "grid.alpha": 1.0,

        "xtick.color": t.chart("axis"),
        "ytick.color": t.chart("axis"),
        "xtick.labelcolor": t.chart("tick"),
        "ytick.labelcolor": t.chart("tick"),
        "xtick.labelsize": t.font_size("eyebrow"),
        "ytick.labelsize": t.font_size("eyebrow"),
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 4,
        "ytick.major.size": 4,
        "xtick.major.width": 1.0,
        "ytick.major.width": 1.0,

        "lines.linewidth": PROFILE_WIDTH,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "lines.markersize": 5,


        "text.color": t.color("ink"),
        "font.family": "sans-serif",
        "font.sans-serif": sans,
        "font.monospace": mono,
        "font.size": t.font_size("body-sm"),

        "patch.edgecolor": t.color("border"),
        "patch.linewidth": 0,
    })
    return t


def series_color(index, t=None):
    return (t or current).series_color(index)


def tick_font():
    """Axis ticks are mono, so digits line up between one plot and the next."""
    return {"family": "monospace"}


def sequential_cmap(name="tapio-sequential", t=None):
    """One hue, light to dark, for spectrograms and heatmaps."""
    t = t or current
    return LinearSegmentedColormap.from_list(name, t.sequential)


def diverging_cmap(name="tapio-diverging", t=None):
    """Blue to gold with a neutral midpoint. Blue is the positive pole."""
    t = t or current
    return LinearSegmentedColormap.from_list(name, t.diverging)


def recency_colors(count, t=None):
    """``(colour, alpha)`` for *count* stacked profiles, newest first.

    Recency is an order, and the reader should see the order in the colour, so
    this is an ordinal ramp rather than eight categorical hues. The ramp has
    three steps and stays clear of the accent, so however many profiles a folder
    holds, none of them can be mistaken for the mean; alpha carries the finer
    ordering when there are more profiles than steps.
    """
    t = t or current
    ramp = t.recency
    if count <= 0:
        return []
    if count == 1:
        return [(ramp[0], 1.0)]
    positions = np.linspace(0, len(ramp) - 1, count)
    alphas = np.linspace(0.9, 0.45, count)
    return [
        (ramp[int(round(position))], float(alpha))
        for position, alpha in zip(positions, alphas)
    ]


def band_color(t=None):
    """The wash beyond a limit, as an RGBA tuple."""
    t = t or current
    return to_rgba(t.chart("band"), t.band_alpha)


def limit_wash(ax, value, direction, color):
    """A limit wash that reaches the edge of the axes and stays there.

    Added with ``add_artist`` rather than ``axhspan`` on purpose: ``axhspan``
    folds the rectangle into the data limits and re-autoscales, which with a
    deliberately oversized wash would blow the y-axis away from the data. An
    artist is clipped to the axes and left out of autoscaling entirely, so the
    wash keeps reaching the frame whatever the caller does with ``set_ylim``
    afterwards.
    """
    reach = 1e6 * max(1.0, abs(value))
    bottom = value if direction == "up" else value - reach
    patch = Rectangle(
        (0, bottom), 1, reach,
        transform=ax.get_yaxis_transform(which="grid"),
        facecolor=color, edgecolor="none", zorder=0,
    )
    return ax.add_artist(patch)


def profile(ax, x, y, lower=None, upper=None, target=None, label=None,
            units="", color=None, extreme=True, t=None):
    """Draw one profile with its limits, the way the system prescribes.

    * limit lines in the limit colour, labelled with their value at the right
      edge, and the region beyond each one washed so the violation is a *shape*
      the eye finds before it reads the axis;
    * the failing samples redrawn on top in the limit colour, so the profile
      stays continuous and the failure is unmistakable;
    * the extreme point marked and labelled with its position, because
      "MIN 55.73 @ 1305 mm" is the number that goes into the maintenance
      conversation.

    Returns the list of artists it added.
    """
    t = t or current
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    added = []

    if color is None:
        color = t.series_color(0)

    limit = t.chart("limit")
    wash = band_color(t)

    # The washes go down first so nothing else has to fight them for z-order.
    if lower is not None:
        added.append(limit_wash(ax, lower, "down", wash))
    if upper is not None:
        added.append(limit_wash(ax, upper, "up", wash))

    # The target is present but recessive, and never red: a target is not an alarm.
    if target is not None:
        added.append(ax.axhline(target, color=t.chart("target"), linestyle=(0, (5, 4)),
                                linewidth=TARGET_WIDTH, zorder=2))

    # Each limit is labelled with its value at the right edge, sitting *inside*
    # the wash on the out-of-spec side of its own line, so the label names the
    # forbidden region rather than floating outside the frame where it would
    # fight the layout for margin.
    for value, side in ((lower, "below"), (upper, "above")):
        if value is None:
            continue
        added.append(ax.axhline(value, color=limit, linewidth=LIMIT_WIDTH, zorder=3))
        added.append(ax.annotate(
            f"{value:g}{units}",
            xy=(1.0, value), xycoords=ax.get_yaxis_transform(),
            xytext=(-5, 4 if side == "above" else -4), textcoords="offset points",
            va="bottom" if side == "above" else "top", ha="right",
            fontsize=t.font_size("eyebrow"),
            color=limit, family="monospace", clip_on=False, zorder=6,
        ))

    added.append(ax.plot(x, y, color=color, linewidth=PROFILE_WIDTH,
                         solid_capstyle="round", solid_joinstyle="round",
                         label=label, zorder=4)[0])

    # Out-of-spec segments, redrawn on top of the base line.
    violation = np.zeros_like(y, dtype=bool)
    if lower is not None:
        violation |= y < lower
    if upper is not None:
        violation |= y > upper
    if violation.any():
        masked = np.where(violation, y, np.nan)
        # Bridge to the neighbouring in-spec sample so the red segment meets the
        # blue line instead of stopping a sample short of the crossing.
        indices = np.flatnonzero(violation)
        for edge in (indices - 1, indices + 1):
            inside = edge[(edge >= 0) & (edge < len(y))]
            masked[inside] = y[inside]
        added.append(ax.plot(x, masked, color=limit, linewidth=VIOLATION_WIDTH,
                             solid_capstyle="round", solid_joinstyle="round",
                             zorder=5)[0])

    if extreme and len(y):
        added.extend(_mark_extreme(ax, x, y, lower, upper, units, t))

    return added


def _mark_extreme(ax, x, y, lower, upper, units, t):
    """Mark and label whichever end of the profile is the one being discussed."""
    low_index = int(np.argmin(y))
    high_index = int(np.argmax(y))

    if upper is not None and y[high_index] > upper:
        index, tag = high_index, "MAX"
    elif lower is not None and y[low_index] < lower:
        index, tag = low_index, "MIN"
    else:
        return []

    color = t.chart("limit")
    marker = ax.plot(x[index], y[index], marker="o", markersize=EXTREME_MARKER,
                     markerfacecolor=t.chart("surface"), markeredgecolor=color,
                     markeredgewidth=2.0, linestyle="none", zorder=7)[0]
    above = tag == "MAX"
    text = ax.annotate(
        f"{tag} {y[index]:.2f}{units} @ {x[index]:.2f}",
        xy=(x[index], y[index]),
        xytext=(0, 12 if above else -12), textcoords="offset points",
        ha="center", va="bottom" if above else "top",
        fontsize=t.font_size("eyebrow"), family="monospace", color=color, zorder=7,
    )
    return [marker, text]


def supporting(ax, x, y, color, alpha=1.0, selected=False, label=None, t=None):
    """One of the individual profiles the mean is drawn from.

    They are context, not the subject, so they run thin and recede. Pass the
    colour and alpha from ``recency_colors``; a selected profile keeps its
    recency colour and gains weight rather than changing hue, because colour
    here carries recency and selection is a state, not an identity.
    """
    return ax.plot(
        x, y,
        color=color,
        linewidth=PROFILE_WIDTH if selected else SUPPORTING_WIDTH,
        alpha=1.0 if selected else alpha,
        label=label,
        zorder=2 if selected else 1,
    )[0]


def excluded(ax, start, end, label=None, t=None):
    """A hatched grey overlay for an excluded region.

    Excluded regions are never removed from the plot — an operator must be able
    to see what was excluded.
    """
    t = t or current
    edge = t.color("border-strong")
    span = ax.axvspan(start, end, facecolor=to_rgba(t.color("sunken"), 0.55),
                      edgecolor=edge, hatch="///", linewidth=0.0,
                      label=label, zorder=1)
    span.set_edgecolor(to_rgba(edge, 0.7))
    return span


def restyle_figure(figure, t=None):
    """Re-apply the chart tokens to a Figure that already exists.

    ``rcParams`` are read when a Figure is constructed, so a figure built under
    one theme keeps that theme's background for life. A canvas that lives as
    long as the window does — which is both of RollView's — therefore has to be
    told, or a night-shift toggle leaves a white plot inside a dark window.
    """
    t = t or current
    figure.set_facecolor(t.color("surface"))
    figure.set_edgecolor(t.color("surface"))
    for ax in figure.axes:
        ax.set_facecolor(t.chart("surface"))
    return figure


def fit(figure, rect=None):
    """``tight_layout``, minus the warning it prints when it cannot win.

    Below a certain canvas size the axis labels and mono tick labels genuinely
    do not fit, and Matplotlib says so on stderr. There is nothing an operator
    can do about a pane they have dragged small, and the fallback margins still
    render a readable chart, so the message is noise in the log window and in
    the test output. Anything that is a real problem — a missing artist, a bad
    limit — surfaces somewhere an operator can act on it.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Tight layout not applied", category=UserWarning
        )
        figure.tight_layout(rect=rect) if rect is not None else figure.tight_layout()


def finish(ax, xlabel=None, ylabel=None, title=None, t=None):
    """The last pass over an axes: labels, mono ticks, square corners.

    Plot frames are square-cornered and sit on the chart surface. The marks are
    labelled directly — a limit line carries its own value at the right edge,
    the extreme carries its position — so nothing here builds a legend.
    """
    t = t or current
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)

    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily("monospace")

    ax.set_facecolor(t.chart("surface"))
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t.chart("axis"))
    ax.grid(True, axis="y", color=t.chart("grid"), linewidth=1.0)
    ax.grid(False, axis="x")

    return ax


