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

* ``use(theme)`` swaps every chart token, ``tab10``-on-white included, and
  picks a column of the mark table — ``screen`` or ``export``.
* ``profile()`` draws the curve, the limit lines, the washes beyond them, the
  out-of-spec segments redrawn on top, and the labelled extreme.
* ``spectrum()`` plots against spatial frequency on a log axis and refuses to
  draw without a named ordinate; ``wavelength_axis()`` adds the reciprocal
  scale along the top, which is the only way wavelength is ever shown.
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
from matplotlib.ticker import AutoMinorLocator

from theme import paths
from theme import tokens as T

# Mark weights come from the token table's mark specification and are in
# *points*, which is what Matplotlib's linewidth argument has always been. A
# pixel is not a portable unit: the same "2 px" line is a different physical
# thickness on a HiDPI laptop, in a screenshot, in a 300 dpi print and in a PDF.
# The table has two columns — screen and export — and `use(preset=...)` picks
# one, so a figure is not thinner in print than it was on screen.
#
# Ask for these through `mark()` rather than binding them at import: the answer
# depends on which preset is in force.
SUPPORTING_ALPHA = 0.5     # how far back the individual profiles sit
MINOR_TICK_SIZE = 2        # half a major tick, for the unlabelled subdivisions

#: The diagonal used for a region that is out of bounds — excluded from the
#: analysis, or beyond an alert limit. One hatch, so the two read as one idea.
#: The diagonal that says "this region does not count" — excluded from the
#: analysis, or beyond an alert limit. One idea, two densities: hatch reads by
#: how much of the region it inks, so the same spacing that is legible across a
#: narrow band is a wall across most of a panel.
HATCH = "///"            # a narrow band
WIDE_HATCH = "/"         # a large region
HATCH_ALPHA = 0.25

#: Matplotlib measures type in points against the figure's dpi, while the token
#: scale is in CSS pixels like every size in the style sheet. A Figure is built
#: at 100 dpi, so a step handed over unconverted renders 39 % larger than the
#: same step does in the interface beside it — which is why the axis labels read
#: bigger than every Qt label on the tab. ``theme.qt`` makes the same conversion
#: for QFont (setPixelSize, not setPointSize); this is that call for the charts.
FIGURE_DPI = 100.0


def points(px, dpi=FIGURE_DPI):
    """A pixel step of the type scale, in the points Matplotlib wants."""
    return px * 72.0 / dpi


_FONT_DIR = paths.asset_dir("fonts", "plex")

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


def mark(name, t=None):
    """One mark weight in points, from the preset in force."""
    return (t or current).mark(name)


def supporting_width(t=None):
    """The weight of one individual profile behind the mean, in points."""
    return (t or current).supporting_mark


def use(theme=T.LIGHT, density=None, preset=None):
    """Point every chart at one theme's tokens. Returns the resolved tokens.

    *preset* is ``screen`` or ``export`` and selects a column of the mark table:
    lines are thinner on paper than on a screen because a printed point is
    smaller than a rendered one, and the system authors both columns rather than
    leaving a figure to be exported at its screen weights.
    """
    global current
    _register_fonts()
    current = T.load(theme=theme, density=density, preset=preset)
    t = current

    sans = _families(t.sans_stack)
    mono = _families(t.mono_stack)

    mpl.rcParams.update({
        "figure.facecolor": t.color("surface"),
        "figure.edgecolor": t.color("surface"),
        "figure.titlesize": points(t.font_size("title-3")),
        "figure.titleweight": "semibold",
        "savefig.facecolor": t.color("surface"),
        "savefig.edgecolor": t.color("surface"),
        # Raster export is opt-in and never below 300 dpi: a raster screenshot
        # of a profile loses exactly the detail the measurement exists to show.
        "savefig.dpi": t.raster_min_dpi,

        "axes.facecolor": t.chart("surface"),
        "axes.edgecolor": t.chart("axis"),
        "axes.linewidth": t.mark("axis"),
        # The chart chrome carries its own label and title inks. They sit near
        # the interface's `ink-muted` and `ink` without being them, and an axis
        # label is the one thing that has to survive the figure being pasted
        # into a mill report on its own.
        "axes.labelcolor": t.chart("label"),
        "axes.labelsize": points(t.font_size("body-sm")),
        "axes.labelpad": points(t.space(1)),
        "axes.titlesize": points(t.font_size("body")),
        "axes.titlecolor": t.chart("title"),
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.prop_cycle": mpl.cycler(color=t.series),
        # Gridlines are hairlines in both directions, and the plot carries a
        # full frame. The system asks for horizontal-only rules and two spines;
        # RollView reads positions off the distance axis as often as values off
        # the hardness one, and a closed frame is what an instrument plot looks
        # like.
        "axes.grid": True,
        "axes.grid.axis": "both",
        "axes.spines.top": True,
        "axes.spines.right": True,
        "axes.axisbelow": True,

        "grid.color": t.chart("grid"),
        "grid.linewidth": t.mark("grid"),
        "grid.alpha": 1.0,

        "xtick.color": t.chart("axis"),
        "ytick.color": t.chart("axis"),
        "xtick.labelcolor": t.chart("tick"),
        "ytick.labelcolor": t.chart("tick"),
        "xtick.labelsize": points(t.font_size("eyebrow")),
        "ytick.labelsize": points(t.font_size("eyebrow")),
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 4,
        "ytick.major.size": 4,
        "xtick.major.width": t.mark("axis"),
        "ytick.major.width": t.mark("axis"),

        "lines.linewidth": t.mark("series"),
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        # Markers are selective — the extreme point, an excluded-region
        # boundary, the hovered sample — never one per point on a 5 000-point
        # profile, which is why this is a size and not a marker style.
        "lines.markersize": t.mark("marker"),


        "text.color": t.color("ink"),
        "font.family": "sans-serif",
        "font.sans-serif": sans,
        "font.monospace": mono,
        "font.size": points(t.font_size("body-sm")),

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
    """Blue to gold with a neutral midpoint. Blue is the positive pole.

    The token file lists the scale blue-first, which is how a swatch row reads;
    a colormap is indexed from its low end, so it is reversed here. Blue is
    positive because the guide says so — and gold is the negative arm because
    red is reserved for out of spec, and a negative correlation is not an alarm.
    """
    t = t or current
    return LinearSegmentedColormap.from_list(name, t.diverging[::-1])


def minor_ticks(ax, axis="x", t=None):
    """Minor tick marks on an axis, and nothing across the panel.

    A distance axis is read at finer intervals than it is labelled at, and the
    marks give the reader those intervals without a second set of rules over
    the profiles — the panel already carries the major grid, and a minor grid
    on top of it is a texture, not information. Half the length of a major
    tick, in the same ink, so they read as subdivisions rather than as ticks
    someone forgot to label.
    """
    t = t or current
    # A log axis brings its own minor locator, and AutoMinorLocator refuses to
    # work on one — it warns and does nothing. Leave those alone: their
    # subdivisions are already the right ones, and only the styling below has to
    # reach them.
    if axis in ("x", "both") and ax.get_xscale() == "linear":
        ax.xaxis.set_minor_locator(AutoMinorLocator())
    if axis in ("y", "both") and ax.get_yscale() == "linear":
        ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.tick_params(
        axis=axis, which="minor",
        length=MINOR_TICK_SIZE, width=t.mark("axis"), color=t.chart("axis"),
    )
    ax.grid(False, axis=axis, which="minor")
    return ax


def supporting_color(t=None):
    """``(colour, alpha)`` for the individual profiles behind the mean.

    One value for all of them. They were drawn down an ordinal ramp so the
    reader could see which was newest, but on a chart whose subject is the mean
    that ordering is not a question anyone is asking, and a stack in eight
    weights reads as eight different kinds of line. They are one kind of thing
    — context — so they are one colour, at the recessive end of the ramp and
    clear of the accent the mean is drawn in.
    """
    t = t or current
    return t.recency[-1], SUPPORTING_ALPHA


def band_color(t=None):
    """The wash beyond a limit, as an RGBA tuple.

    One token, ``limit-band``, authored as a CSS colour with its alpha in it —
    the same string the CSS and the guide use. Splitting it here rather than
    carrying a hex and an alpha separately is what keeps it comparable with the
    file it came from.
    """
    t = t or current
    return to_rgba(*t.limit_band)


def limit_line_color(t=None):
    """The limit line: one step deeper on the red ramp than a failing fill.

    A mark that failed is filled with ``chart("limit")``, so a line in the same
    hex is the same mark. Taken from the ramp by index rather than named, so it
    stays one step deeper if either token moves.
    """
    t = t or current
    ramp = t.ramp_steps("red")
    index = [value.upper() for value in ramp].index(t.chart("limit").upper())
    return ramp[min(index + 1, len(ramp) - 1)]


def limit_wash(ax, value, direction, color, hatch_color=None):
    """A limit wash that reaches the edge of the axes and stays there.

    Added with ``add_artist`` rather than ``axhspan`` on purpose: ``axhspan``
    folds the rectangle into the data limits and re-autoscales, which with a
    deliberately oversized wash would blow the y-axis away from the data. An
    artist is clipped to the axes and left out of autoscaling entirely, so the
    wash keeps reaching the frame whatever the caller does with ``set_ylim``
    afterwards.

    Pass *hatch_color* for the diagonal fill the excluded regions use. A flat
    tint has to be strong enough to be seen, and on a chart where the region
    beyond the limits is most of the panel that much tint swamps the data; a
    hatch reads as "out of bounds" at a fraction of the ink, and says it in the
    vocabulary the profile chart already uses for a region that does not count.
    """
    reach = 1e6 * max(1.0, abs(value))
    bottom = value if direction == "up" else value - reach
    patch = Rectangle(
        (0, bottom), 1, reach,
        transform=ax.get_yaxis_transform(which="grid"),
        facecolor=color, edgecolor="none", zorder=0,
    )
    if hatch_color is not None:
        patch.set_hatch(WIDE_HATCH)
        patch.set_linewidth(0.0)
        # Matplotlib draws a hatch in the patch's *edge* colour.
        patch.set_edgecolor(to_rgba(hatch_color, HATCH_ALPHA))
    return ax.add_artist(patch)


def profile(ax, x, y, target=None, label=None, color=None, width=None, t=None):
    """Draw one profile: the curve, and a target line if there is one.

    Alert limits are deliberately not drawn. RollView's limits are set on
    summary statistics rather than on the trace, and the stat tiles above the
    chart state each one next to the value it judges — which says *which*
    statistic failed. Two lines across the plot restated that in the one place
    where it competed with the data it was judging.

    ``width`` overrides the system's mark weight, for an installation that has
    asked for a different one in local settings. Leave it None otherwise.

    Returns the list of artists it added.
    """
    t = t or current
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    added = []

    if color is None:
        color = t.series_color(0)

    # The target is present but recessive, and never red: a target is not an alarm.
    if target is not None:
        added.append(ax.axhline(target, color=t.chart("target"),
                                linestyle=(0, t.dash("target")),
                                linewidth=t.mark("target"), zorder=2))

    added.append(ax.plot(x, y, color=color,
                         linewidth=t.mark("series") if width is None else width,
                         solid_capstyle="round", solid_joinstyle="round",
                         label=label, zorder=4)[0])

    return added


def supporting(ax, x, y, color, alpha=1.0, selected=False, label=None,
               selected_width=None, t=None):
    """One of the individual profiles the mean is drawn from.

    They are context, not the subject, so they run thin and recede. Pass the
    colour and alpha from ``supporting_color``; a selected profile keeps that
    colour and gains weight rather than changing hue, because selection is a
    state and not a different kind of line.

    ``selected_width`` overrides the weight the selected one gains; the
    unselected ones stay recessive whatever an installation asks for, since
    that is what makes the mean readable over them.
    """
    t = t or current
    if selected:
        line_width = t.mark("series") if selected_width is None else selected_width
    else:
        line_width = t.supporting_mark
    return ax.plot(
        x, y,
        color=color,
        linewidth=line_width,
        alpha=1.0 if selected else alpha,
        label=label,
        zorder=2 if selected else 1,
    )[0]


def _plain(value, _position=None):
    """A tick label as a number a mill engineer would write.

    ``0.5 1 2 5 10 20``, not ``10^0 10^1``. Matplotlib's default log formatter
    is scientific notation, which is the right answer for eight decades of
    physics and the wrong one for two decades of spatial frequency: an operator
    matching a peak against a 1450 mm press roll reads the number, not the
    exponent.
    """
    if value <= 0:
        return ""
    if value >= 1:
        return f"{value:.0f}"
    return f"{value:g}"


def _log_ticks(axis, t):
    """Decade ticks plus the 2 and 5 between them, labelled as plain numbers.

    A spectrum rarely spans more than two or three decades, and decade labels
    alone leave most of the axis unlabelled — which is what makes a reader
    interpolate by eye across the widest part of the plot.
    """
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    axis.set_major_locator(LogLocator(base=10.0, subs=(1.0, 2.0, 5.0)))
    axis.set_major_formatter(FuncFormatter(_plain))
    axis.set_minor_locator(LogLocator(base=10.0, subs="auto"))
    # The minors are subdivisions to interpolate against, not more numbers.
    axis.set_minor_formatter(NullFormatter())


def spectrum(ax, frequencies, amplitudes, quantity, unit, color=None, t=None):
    """One spectrum: an unfilled line against spatial frequency, on a log axis.

    Refuses to draw without a named quantity and its unit, because the ordinate
    is what decides how a peak may be read. "Intensity" is not a quantity, and
    neither is "relative" or "normalised" without a stated reference — so this
    asks for both rather than letting a chart ship without them.

    Three rules from the system are enforced here rather than remembered:

    * **Spatial frequency is the coordinate**, in 1/m, on a log axis. Wavelength
      is a *second* scale (``wavelength_axis``), never a relabelling of this one:
      λ = 1/f relabels the ticks, but a spectral density has to be transformed
      with the Jacobian, S_λ(λ) = S_f(1/λ)/λ², so relabelled ticks describe a
      quantity the ordinate is not.
    * **The line is not filled.** Area under a spectrum has a meaning — for a
      density, the integral over frequency is variance — so a fill invites an
      area reading of a figure that is not showing an area. On a log axis the
      screen area is not proportional to the integral in any case.
    * **The zero-frequency bin is not a spatial frequency.** It carries the mean
      level, which the profile chart above already states, and a log axis has
      nowhere to put it.

    Returns the line.
    """
    if not quantity or not unit:
        raise ValueError(
            "a spectrum needs a named quantity and a unit on its ordinate: "
            "a peak height cannot be read without them"
        )

    t = t or current
    frequencies = np.asarray(frequencies, dtype=float)
    amplitudes = np.asarray(amplitudes, dtype=float)
    periodic = frequencies > 0

    ax.set_xscale(t.spectral["xScale"])
    line = ax.plot(
        frequencies[periodic], amplitudes[periodic],
        color=color if color is not None else t.series_color(0),
        linewidth=t.mark("series"),
        solid_capstyle="round", solid_joinstyle="round",
        zorder=4,
    )[0]
    # Subdivisions belong on a logarithmic axis, where the gap between two
    # labelled decades is most of the panel and a reader has to interpolate
    # across it. A log scale places its own minor locator; all this does is give
    # those marks the system's weight and ink. Marks on the axis, not rules
    # across it — same as the distance axis above, and for the same reason.
    _log_ticks(ax.xaxis, t)
    ax.tick_params(
        axis="x", which="minor",
        length=MINOR_TICK_SIZE, width=t.mark("axis"), color=t.chart("axis"),
    )
    ax.grid(False, axis="x", which="minor")
    return line


def wavelength_axis(ax, label=None, t=None):
    """The reciprocal wavelength scale, along the top edge.

    Wavelength is what names machine elements, so the chart carries it — as its
    own axis with its own ticks, sharing the frequency axis's *position* and not
    its ordinate. The alternative RollView used to offer, rewriting the
    frequency axis's tick labels as wavelengths and renaming the axis with them,
    is the one thing the system says never to do: the numbers under the curve
    then belong to a quantity the y-axis is not showing.

    Returns the secondary axes.
    """
    t = t or current
    reciprocal = t.spectral["reciprocalAxis"]
    # 1/m to the unit the system asks for along the top.
    per_metre = {"mm": 1000.0, "cm": 100.0, "m": 1.0}[reciprocal["unit"]]

    def to_wavelength(frequency):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(frequency == 0, np.inf, per_metre / frequency)

    top = ax.secondary_xaxis(
        "top" if reciprocal["position"] == "top" else "bottom",
        functions=(to_wavelength, to_wavelength),   # its own inverse
    )
    top.set_xlabel(
        label or f"{reciprocal['quantity']} ({reciprocal['unit']})".capitalize()
    )
    _log_ticks(top.xaxis, t)
    top.tick_params(colors=t.chart("axis"), labelcolor=t.chart("tick"))
    top.tick_params(
        which="minor", length=MINOR_TICK_SIZE,
        width=t.mark("axis"), color=t.chart("axis"),
    )
    top.xaxis.label.set_color(t.chart("label"))
    for tick in top.get_xticklabels():
        tick.set_fontfamily("monospace")
    return top


def excluded(ax, start, end, label=None, t=None):
    """A hatched grey overlay for an excluded region.

    Excluded regions are never removed from the plot — an operator must be able
    to see what was excluded.
    """
    t = t or current
    edge = t.color("border-strong")
    span = ax.axvspan(start, end, facecolor=to_rgba(t.color("surface-sunken"), 0.55),
                      edgecolor=edge, hatch=HATCH, linewidth=0.0,
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
    for side in ("left", "bottom", "top", "right"):
        ax.spines[side].set_visible(True)
        ax.spines[side].set_color(t.chart("axis"))
    ax.grid(True, axis="both", color=t.chart("grid"), linewidth=t.mark("grid"))

    # Ink from the token table rather than from rcParams. use() puts the same
    # values there, so on screen this changes nothing — but it is what lets a
    # caller finish an axes against a table that is *not* the live one, which
    # is how a plot exports light out of a dark session without touching
    # process-wide state that the GUI thread is reading at the same time.
    ax.tick_params(axis="both", colors=t.chart("axis"), labelcolor=t.chart("tick"))
    ax.xaxis.label.set_color(t.chart("label"))
    ax.yaxis.label.set_color(t.chart("label"))
    ax.title.set_color(t.chart("title"))

    return ax


