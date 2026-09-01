# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Applies the Tapio Design System to a Qt application.

Three things do most of the work:

* **Fusion**, wrapped in ``RollViewStyle``. The native Windows style silently
  ignores much of a style sheet, which is a large part of why the applications
  looked unstyled; the wrapper is there for the handful of behaviours a style
  sheet cannot reach, starting with Fusion's menu-style combo box popup.
* **The bundled Plex fonts**, registered with ``QFontDatabase`` so the app does
  not depend on what the operator happens to have installed.
* **Dynamic properties** for variants and states, so the stylesheet keeps
  ownership of colour: ``set_variant(button, "primary")``,
  ``set_state(label, "bad")``.

A widget does not restyle itself when a dynamic property changes, so every
setter here re-polishes. Use these helpers rather than ``setProperty``.
"""

import os
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QProxyStyle,
    QStyle,
    QWidget,
)

from theme import icons
from theme import paths
from theme import tokens as T

_QSS_PATH = paths.theme_file("rollview.qss")
_FONT_DIR = paths.asset_dir("fonts", "plex")

_FONT_FILES = (
    "IBMPlexSans-Light.ttf",
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)

# Set by apply(); everything downstream reads the live tokens from here rather
# than loading its own copy, so one call swaps the whole application.
current = T.load()
# What was *asked* for, which is not the same thing: "system" resolves to one of
# the two tables, and something has to remember that it was "system" so a later
# change of desktop appearance can be followed.
requested = T.LIGHT
_fonts_loaded = False


def desktop_scheme():
    """What the desktop says it is set to, as a ``Qt.ColorScheme``.

    The one place the platform is asked, so a test can answer for it: the
    offscreen platform ignores ``setColorScheme`` and reports ``Unknown``
    whatever it is told, which leaves no other way to exercise a dark desktop.
    """
    app = QApplication.instance()
    if app is None:
        return Qt.ColorScheme.Unknown
    return app.styleHints().colorScheme()


def resolve(theme):
    """Turn a preference into one of the two token tables.

    ``system`` asks the desktop. Platforms and sessions that do not report one —
    a bare X session, the offscreen platform — answer ``Unknown``, and that
    resolves to light: the product default rather than a guess.
    """
    if theme != T.SYSTEM:
        return theme if theme in T.THEMES else T.LIGHT
    return T.DARK if desktop_scheme() == Qt.ColorScheme.Dark else T.LIGHT


# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------

def load_fonts():
    """Register the bundled Plex faces. Returns the families Qt accepted."""
    global _fonts_loaded
    families = set()
    for filename in _FONT_FILES:
        path = os.path.join(_FONT_DIR, filename)
        if not os.path.exists(path):
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id != -1:
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    _fonts_loaded = True
    # What Qt can resolve just changed.
    _family_cache.clear()
    _font_cache.clear()
    return sorted(families)


# Resolving a family means enumerating every font Qt knows about, and building a
# QFont from a scale step means doing that plus the QFont construction. Both are
# asked for per *table cell per repaint* — a model returns mono_font() from
# Qt.FontRole — which during a splitter drag came to thousands of font-database
# scans a second. Neither answer changes until the theme does, so both are
# cached and both caches are dropped in apply().
_family_cache = {}
_font_cache = {}


def _first_available(stack):
    """The first family in a token stack that Qt can actually resolve."""
    key = tuple(stack)
    cached = _family_cache.get(key)
    if cached is not None:
        return cached

    available = set(QFontDatabase.families())
    resolved = next((family for family in stack if family in available), stack[-1])
    _family_cache[key] = resolved
    return resolved


def sans_family(t=None):
    return _first_available((t or current).sans_stack)


def mono_family(t=None):
    return _first_available((t or current).mono_stack)


def font(step, t=None):
    """A ``QFont`` for one step of the type scale.

    Letter-spacing, capitalisation and tabular figures cannot be expressed in a
    Qt style sheet, so the steps that need them are built here instead.
    """
    t = t or current
    cached = _font_cache.get(("scale", step, t.theme))
    if cached is not None:
        # A copy, so a caller adjusting the size cannot reach into the cache.
        return QFont(cached)

    spec = t.font(step)
    family = mono_family(t) if spec["family"] == "mono" else sans_family(t)
    result = QFont(family)
    # The scale is in pixels, and so is every size in the style sheet. QFont's
    # size argument is points, which on a 96 dpi screen would render each step a
    # third too large and out of step with the sheet.
    result.setPixelSize(spec["size"])
    result.setWeight(QFont.Weight(spec["weight"]))
    if spec.get("tracking"):
        result.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spec["tracking"])
    if spec.get("uppercase"):
        result.setCapitalization(QFont.Capitalization.AllUppercase)
    # `tabular` needs no code: every face in the mono stack is monospaced, so
    # its digits are already the same width. PySide6 exposes QFont.setFeature
    # only through a QFont.Tag it gives Python no way to construct, so asking
    # for `tnum` explicitly is not available here — which is why the data steps
    # are pinned to the mono family rather than left to a font feature.
    _font_cache[("scale", step, t.theme)] = result
    return QFont(result)


#: A field sized to exactly its own text clips the last glyph — the advance
#: width a font reports and the pixels it actually inks are not the same number.
FIELD_SLACK = 6


def numeric_field_width(characters, sample=None, t=None):
    """Pixels a mono input needs to show *characters* digits without clipping.

    Pass ``sample`` for anything else that has to fit — a placeholder, usually —
    and the wider of the two wins.

    Widths for these were picked against the unstyled metrics and do not survive
    the theme: the style sheet gives every QLineEdit 12 px of padding a side, so
    a field sized for four digits shows two and a half. Measuring the face the
    field actually renders in survives a change of face or size too.
    """
    from PySide6.QtGui import QFontMetrics

    t = t or current
    # The style sheet gives a data field the mono *family* but no size, so it
    # renders at the application font size. Measuring a fixed scale step instead
    # would come out right only while that step shares the base size.
    face = QFont(mono_family(t))
    face.setPixelSize(t.base_text_size)
    metrics = QFontMetrics(face)
    text = metrics.horizontalAdvance("0" * characters)
    if sample:
        text = max(text, metrics.horizontalAdvance(sample))
    padding = t.space(3) * 2      # the QLineEdit rule's horizontal padding
    chrome = 2 * 2                # 1 px border a side, doubled by the focus ring
    return text + padding + chrome + FIELD_SLACK


def tree_column_width(characters, view, t=None):
    """Pixels a tree column needs for *characters* of a mono identifier.

    Use this rather than ``ResizeToContents`` for a column of fixed-format
    values. ResizeToContents asks the *model* how wide its contents are, and a
    QFileSystemModel answers for every row it has loaded — not just the visible
    ones — including the icon and indentation the platform style reserves. Those
    reservations differ enough between platforms that the same column comes out
    reasonable on one and absurdly wide on another. Measuring the text is the
    same answer everywhere.
    """
    from PySide6.QtGui import QFontMetrics

    t = t or current
    face = QFont(mono_family(t))
    face.setPixelSize(t.base_text_size)
    text = QFontMetrics(face).horizontalAdvance("0" * characters)
    padding = t.space(2) * 2       # the item rule's horizontal padding
    return text + padding + view.indentation() + FIELD_SLACK


def style_header(header, t=None):
    """Give an item view's header the eyebrow face, and centre its labels.

    The face is set here and *not* in the style sheet, which is the whole point:
    a `font-*` rule on `QHeaderView::section` applies when the section is
    painted, but Qt measures the label rect from the widget's own font. Declare
    it in the sheet and the header is laid out for 13 px sans and drawn in 11 px
    mono, so the label ends up above centre no matter what the alignment says.
    One font, used for both, is what actually centres it.

    Height is left alone deliberately. `min-height` on the section anchors the
    label box to the top and lets the extra space fall below it, and setting a
    height on the header *widget* grows the widget past its sections, which then
    paint against its top edge. The section sizes itself from this font.
    """
    t = t or current
    face = font("eyebrow", t)
    # The eyebrow uppercases its text, and a column heading can carry a unit:
    # "Profile length [m]" becomes "[M]", which is mega and not metres. A unit
    # symbol is not a style, so the heading keeps the face and the tracking and
    # loses the capitalisation.
    face.setCapitalization(QFont.Capitalization.MixedCase)
    header.setFont(face)
    header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    return header


def mono_font(step="body-sm", t=None):
    """The mono face at one step of the scale.

    For the measured values inside item views, which a style sheet can reach
    only through ``QTreeView::item`` — and that rule cannot pick out a single
    column. Models return this from ``Qt.FontRole`` instead.
    """
    t = t or current
    key = ("mono", step, t.theme)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached

    result = QFont(mono_family(t))
    result.setPixelSize(t.font_size(step))
    result.setWeight(QFont.Weight(400))
    _font_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------

def build_palette(t):
    """A ``QPalette`` from the tokens.

    Fusion draws plenty of chrome straight from the palette — item view
    backgrounds, menu highlights, the Matplotlib toolbar's icon recolouring —
    so the palette has to agree with the style sheet rather than being left at
    whatever the desktop supplies.
    """
    def c(role):
        return QColor(t.color(role))

    palette = QPalette()
    disabled_ink = QColor(T.mix(t.color("ink-muted"), t.color("surface"), 0.55))

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, c("bg"))
        palette.setColor(group, QPalette.ColorRole.WindowText, c("ink"))
        palette.setColor(group, QPalette.ColorRole.Base, c("surface"))
        palette.setColor(group, QPalette.ColorRole.AlternateBase, c("surface"))
        palette.setColor(group, QPalette.ColorRole.Text, c("ink"))
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, c("ink-muted"))
        palette.setColor(group, QPalette.ColorRole.Button, c("surface"))
        palette.setColor(group, QPalette.ColorRole.ButtonText, c("ink"))
        palette.setColor(group, QPalette.ColorRole.BrightText, c("bad-mark"))
        palette.setColor(group, QPalette.ColorRole.Highlight, c("accent-soft"))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, c("ink"))
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, c("raised"))
        palette.setColor(group, QPalette.ColorRole.ToolTipText, c("ink"))
        palette.setColor(group, QPalette.ColorRole.Link, c("link"))
        palette.setColor(group, QPalette.ColorRole.LinkVisited, c("accent-active"))
        palette.setColor(group, QPalette.ColorRole.Light, c("surface"))
        palette.setColor(group, QPalette.ColorRole.Midlight, c("sunken"))
        palette.setColor(group, QPalette.ColorRole.Mid, c("border"))
        palette.setColor(group, QPalette.ColorRole.Dark, c("border-strong"))
        palette.setColor(group, QPalette.ColorRole.Shadow, c("border-strong"))

    group = QPalette.ColorGroup.Disabled
    palette.setColor(group, QPalette.ColorRole.WindowText, disabled_ink)
    palette.setColor(group, QPalette.ColorRole.Text, disabled_ink)
    palette.setColor(group, QPalette.ColorRole.ButtonText, disabled_ink)
    palette.setColor(group, QPalette.ColorRole.Window, c("bg"))
    palette.setColor(group, QPalette.ColorRole.Base, c("sunken"))
    palette.setColor(group, QPalette.ColorRole.Button, c("surface"))
    palette.setColor(group, QPalette.ColorRole.Highlight, c("sunken"))
    palette.setColor(group, QPalette.ColorRole.HighlightedText, disabled_ink)
    return palette


# ---------------------------------------------------------------------------
# stylesheet
# ---------------------------------------------------------------------------

def build_stylesheet(t):
    """Substitute the token table into the QSS template."""
    with open(_QSS_PATH, encoding="utf-8") as handle:
        template = Template(handle.read())

    surface = t.color("surface")
    control = t.control_height
    # Qt adds the border to min-height, so the inner box is the token height
    # minus the two 1 px borders. Focus swaps those for 2 px ones, and padding
    # drops by the same amount so nothing shifts under the ring.
    control_inner = control - 2
    accent = t.color("accent")

    values = {
        # surfaces and ink
        "bg": t.color("bg"),
        "surface": surface,
        "sunken": t.color("sunken"),
        "sunken_pressed": T.mix(t.color("border"), surface, 0.85),
        "raised": t.color("raised"),
        "border": t.color("border"),
        "border_strong": t.color("border-strong"),
        "ink": t.color("ink"),
        "ink_secondary": t.color("ink-secondary"),
        "ink_muted": t.color("ink-muted"),
        "ink_disabled": T.mix(t.color("ink-muted"), surface, 0.55),
        # accent
        "accent": accent,
        "accent_hover": t.color("accent-hover"),
        "accent_active": t.color("accent-active"),
        "accent_soft": t.color("accent-soft"),
        "accent_soft_pressed": T.mix(accent, t.color("accent-soft"), 0.2),
        "accent_ink": t.color("accent-ink"),
        "focus": t.color("focus"),
        # status
        "good": t.color("good"),
        "warn": t.color("warn"), "warn_soft": t.color("warn-soft"), "warn_mark": t.color("warn-mark"),
        "bad": t.color("bad"), "bad_soft": t.color("bad-soft"), "bad_mark": t.color("bad-mark"),
        # type
        "mono": mono_family(t),
        "body_lg": t.font_size("body-lg"),
        "body_sm": t.font_size("body-sm"),
        "label": t.font_size("label"),
        "eyebrow": t.font_size("eyebrow"),
        # space
        "data": t.font_size("data"),
        "data_large": DATA_LARGE_SIZE,
        "data_value": DATA_VALUE_SIZE,
        "title_3": t.font_size("title-3"),
        "s1": t.space(1), "s2": t.space(2), "s3": t.space(3),
        "s4": t.space(4), "s6": t.space(6),
        "s1_focus": t.space(1) - 1,
        "s3_focus": t.space(3) - 1,
        "s4_focus": t.space(4) - 1,
        # radius
        "r_sm": t.radius("sm"), "r_md": t.radius("md"), "r_lg": t.radius("lg"),
        # metrics
        "control_inner": control_inner,
        # Rows carry no vertical padding, so this is the layout's row height
        # less the 1 px hairline under each one. Header sections size themselves
        # from the eyebrow font style_header() gives them.
        "row_inner": t.row_height - 1,

        "tab_height": control - 12,
        "check_target": min(t.min_target, control),
        "dialog_button_width": 96,
        # One handle size, spent three ways, so the pieces cannot drift apart:
        # the widget's minimum, the handle's own box, and how far it overhangs
        # the groove.
        "slider_height": SLIDER_HANDLE_SIZE + 2,
        "slider_handle_border": SLIDER_HANDLE_BORDER,
        "slider_handle_inner": SLIDER_HANDLE_SIZE - SLIDER_HANDLE_BORDER * 2,
        "slider_handle_radius": SLIDER_HANDLE_SIZE // 2,
        "slider_handle_margin": (SLIDER_HANDLE_SIZE - SLIDER_GROOVE_SIZE) // 2,
        # baked glyphs
        "chevron_icon": icons.write_png("chevron-down", 12, t.color("ink-muted"), stroke=2.0),
        "check_icon": icons.write_png("check", 13, t.color("accent-ink"), stroke=3.0),
        "sort_down_icon": icons.write_png("chevron-down", 10, t.color("ink-muted"), stroke=2.4),
        "sort_up_icon": icons.write_png("chevron-up", 10, t.color("ink-muted"), stroke=2.4),
    }
    return template.substitute(values)


# ---------------------------------------------------------------------------
# style
# ---------------------------------------------------------------------------

class RollViewStyle(QProxyStyle):
    """Fusion, with its combo box drop-down brought back to a drop-down.

    Fusion answers ``SH_ComboBox_Popup`` with true for every non-editable combo,
    which turns the list into a macOS-style menu: it opens *over* the control
    with the current item under the cursor rather than below it, ``maxVisibleItems``
    stops meaning anything, and the moment the list is taller than the room left
    on the screen the overflow is reached through two 10 px auto-scrolling arrow
    strips instead of a scrollbar. Choose the last colour in a list and reopen
    it and the list is pinned to the top of the screen with its first entries
    behind an arrow — options that look simply missing — and the wheel then
    moves it a whole row at a time.

    A settings form wants the ordinary control: the list below the field it
    belongs to, sized to its own items, with the themed scrollbar when there are
    more of them than fit, and scrolling by the pixel rather than by the row.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def polish(self, target):
        # Overloaded in Qt — QWidget, QApplication and QPalette all land here,
        # and the palette overload has to give its argument back.
        polished = super().polish(target)
        if isinstance(target, QComboBox):
            # A drop-down is a list of words, not a table of rows to land on
            # exactly; per-item scrolling makes a short list lurch.
            target.view().setVerticalScrollMode(
                QAbstractItemView.ScrollMode.ScrollPerPixel
            )
        if isinstance(target, QAbstractItemView):
            # Every row in this system is as tall as the style sheet says, and
            # a view that was asked for a row rectangle before the sheet
            # reached it has already laid its rows out at the plain style's
            # height and will not ask again. The rows then paint at the
            # sheet's height on top of one another — the settings sidebar came
            # up as five overlapping lines — until something repolishes the
            # tree, which is why changing the theme appeared to fix it.
            #
            # Scheduled rather than done here: the sheet's own polish runs
            # after this one, so the measurement is only right on the way back
            # out to the event loop.
            target.scheduleDelayedItemsLayout()
        return polished


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def apply(app=None, theme=T.LIGHT):
    """Apply the system to *app*. Returns the resolved ``Tokens``.

    Safe to call again at runtime: a night-shift toggle costs one call.

    *theme* may be ``system``, in which case the desktop decides; the returned
    tokens are always one of the two real tables.
    """
    global current, requested

    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("theme.qt.apply() needs a QApplication")

    if not _fonts_loaded:
        load_fonts()

    requested = theme
    current = T.load(theme=resolve(theme))
    icons.clear_cache()
    _family_cache.clear()
    _font_cache.clear()

    app.setStyle(RollViewStyle("Fusion"))
    app.setPalette(build_palette(current))
    app.setStyleSheet(build_stylesheet(current))

    # The application font is what every widget inherits, now that the style
    # sheet no longer declares one globally.
    #
    # It goes *after* the style sheet, and that order is the whole point.
    # setStyleSheet() installs QStyleSheetStyle, which is a style change, and a
    # style change re-seeds Qt's per-class widget font hash from the platform
    # theme. Those per-class entries — QMenuBar, QTreeView, QCheckBox, QMenu,
    # QToolButton, QListView — outrank the plain application font, so a font set
    # before the sheet was silently overruled for exactly those classes and they
    # came up in the desktop's font at the desktop's size. It looked like the
    # startup state was correct and changing the theme shrank the interface; in
    # fact the startup state was wrong and any later apply() fixed it, because
    # by then the sheet was already installed.
    base = QFont(sans_family(current))
    base.setPixelSize(current.base_text_size)
    base.setWeight(QFont.Weight(400))
    app.setFont(base)
    return current


# ---------------------------------------------------------------------------
# property helpers
# ---------------------------------------------------------------------------

def _repolish(widget):
    """Qt does not restyle on a property change; make it — children included.

    The subtree is not thoroughness for its own sake. The style sheet keys
    colour off ancestors — ``QWidget#statTile[state="bad"] QLabel`` is what
    takes the eyebrow and the unit red along with the number — and Qt caches
    each widget's resolved rules until *that widget* is repolished. Repolishing
    only the container therefore leaves every label inside it painted for the
    state the container was in before: a tile that crossed its alert limit came
    up with a red number in a red box and a grey label beside it, and stayed
    that way until the next theme change polished the whole tree and made it
    look as though nothing had ever been wrong.
    """
    for target in [widget] + widget.findChildren(QWidget):
        style = target.style()
        style.unpolish(target)
        style.polish(target)
        # Through QWidget, because an item view's own update() is Qt's
        # update(index) and PySide hides the no-argument one behind it: a
        # subtree with a list or a tree anywhere in it would raise instead of
        # repainting.
        QWidget.update(target)


def set_property(widget, name, value):
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    _repolish(widget)


def set_variant(widget, variant):
    """``primary`` | ``secondary`` | ``ghost`` | ``danger``.

    One primary per view — the single most likely next action. Secondary is the
    default and needs no call.
    """
    set_property(widget, "variant", variant)


# The slider handle, outer size including its border. Qt sizes a styled QSlider
# from its groove alone, so the widget has to be told to leave room for this or
# it clips the handle.
SLIDER_HANDLE_SIZE = 16
SLIDER_HANDLE_BORDER = 2
SLIDER_GROOVE_SIZE = 4      # the groove rule's height; the handle's overhang is
                            # measured against the groove's content box, not its
                            # bordered one, so this is the 4 px and not the 6.

# The guide's display-sized readout, for a screen carrying one or two numbers.
DATA_LARGE_SIZE = 27
# The size the profile tab's seven statistics fit across one row at. Still the
# mono face, still tabular, still the only weight above 400 in the product.
DATA_VALUE_SIZE = 19

_ROLE_STEPS = {
    "data": "data",
    "dataLarge": "data",
    "dataValue": "data",
    "eyebrow": "eyebrow",
    "label": "label",
    "hint": "body-sm",
    "unit": "body-sm",
    "title": "title-3",
}


def set_role(widget, role):
    """``data`` | ``dataLarge`` | ``eyebrow`` | ``label`` | ``hint`` | ``title`` | ``unit``.

    Sets the property the style sheet keys the type and colour off. The type is
    *not* applied here: with an application style sheet in place, Qt re-resolves
    a widget's font when it polishes it and discards anything ``setFont`` put
    there, so a role applied in code reverts the moment the widget is shown.

    Fonts built by ``font()`` still work where Qt never polishes them — most
    usefully as a model's ``Qt.FontRole``, which the delegate honours at paint
    time. That is how the item views get their mono columns.
    """
    set_property(widget, "role", role)


def set_state(widget, state):
    """``good`` | ``warn`` | ``bad`` | ``idle``, or ``None`` to clear."""
    set_property(widget, "state", state)


def set_invalid(widget, invalid):
    """The error state is never colour-only: this is the border half of it."""
    set_property(widget, "invalid", "true" if invalid else "false")


def set_panel(widget, kind="true"):
    """Give a container the card treatment: surface, 1 px border, 8 px radius.

    Depth is carried by the border and the surface lightness, never by a
    shadow — Qt renders shadows inconsistently and a black shadow on the dark
    theme's near-black ground is invisible.
    """
    set_property(widget, "panel", kind)


# ---------------------------------------------------------------------------
# spacing
# ---------------------------------------------------------------------------

def _step(value, t):
    """One step of the space scale, with 0 meaning 0 px rather than a step."""
    return 0 if not value else t.space(value)


def pad(target, left, top=None, right=None, bottom=None, t=None):
    """Contents margins in *scale steps*, not pixels.

    Qt's own edge order, so it reads the same as the call it replaces::

        pad(layout, 3)              12 px all round
        pad(layout, 2, 1)           8 px left and right, 4 px top and bottom
        pad(layout, 2, 1, 2, 2)     left, top, right, bottom, named individually

    ``0`` means no margin, which is why it is not a step on the scale.

    Nothing corrects a layout that never asks: Qt's defaults are 11 px margins
    and 6 px spacing, and neither is on the 4 px grid. That is the whole reason
    this exists — colour and type reach a new screen through the style sheet
    without being asked, and density is the one part of the system that cannot,
    so it has to be one short call instead of four token lookups.
    """
    t = t or current
    if top is None:
        top = left
    if right is None:
        right = left
    if bottom is None:
        bottom = top
    target.setContentsMargins(
        _step(left, t), _step(top, t), _step(right, t), _step(bottom, t)
    )
    return target


def gap(layout, spacing, vertical=None, t=None):
    """Layout spacing in scale steps.

    ``gap(layout, 2)`` is 8 px. Pass *vertical* for a grid whose rows and
    columns want different spacing; on any other layout the two are the same
    number and Qt has only the one setter.
    """
    t = t or current
    if vertical is None:
        layout.setSpacing(_step(spacing, t))
    else:
        layout.setHorizontalSpacing(_step(spacing, t))
        layout.setVerticalSpacing(_step(vertical, t))
    return layout


def tokens():
    """The live token table. Call it; do not bind ``current`` at import time."""
    return current


__all__ = [
    "apply", "tokens", "resolve", "requested", "desktop_scheme", "font", "mono_font", "style_header",
    "RollViewStyle",
    "numeric_field_width", "tree_column_width",
    "sans_family", "mono_family", "pad", "gap",
    "set_variant", "set_role", "set_state", "set_invalid", "set_panel",
    "build_palette", "build_stylesheet", "load_fonts",
]
