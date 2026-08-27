# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Applies the Tapio Design System to a Qt application.

Three things do most of the work:

* **Fusion.** The native Windows style silently ignores much of a style sheet,
  which is a large part of why the applications looked unstyled.
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
from PySide6.QtWidgets import QApplication

from theme import icons
from theme import tokens as T

_THEME_DIR = os.path.dirname(os.path.abspath(__file__))
_QSS_PATH = os.path.join(_THEME_DIR, "rollview.qss")
_FONT_DIR = os.path.join(os.path.dirname(_THEME_DIR), "assets", "fonts", "plex")

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
_fonts_loaded = False


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
    cached = _font_cache.get(("scale", step, t.theme, t.density))
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
    _font_cache[("scale", step, t.theme, t.density)] = result
    return QFont(result)


def numeric_field_width(characters, t=None):
    """Pixels a mono input needs to show *characters* digits without clipping.

    Widths for these were picked against the unstyled metrics and do not survive
    the theme: the style sheet gives every QLineEdit 12 px of padding a side, so
    a field sized for four digits shows two and a half. Measuring the face the
    field actually renders in survives a change of font, size or density too.
    """
    from PySide6.QtGui import QFontMetrics

    t = t or current
    # The style sheet gives a data field the mono *family* but no size, so it
    # renders at the application font size. Measuring a fixed scale step instead
    # would come out right only at whichever density happens to share it.
    face = QFont(mono_family(t))
    face.setPixelSize(t.base_text_size)
    text = QFontMetrics(face).horizontalAdvance("0" * characters)
    padding = t.space(3) * 2      # the QLineEdit rule's horizontal padding
    chrome = 2 * 2                # 1 px border a side, doubled by the focus ring
    return text + padding + chrome


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
    key = ("mono", step, t.theme, t.density)
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
        "inverse": t.color("inverse"),
        "border": t.color("border"),
        "border_strong": t.color("border-strong"),
        "ink": t.color("ink"),
        "ink_secondary": t.color("ink-secondary"),
        "ink_muted": t.color("ink-muted"),
        "ink_inverse": t.color("ink-inverse"),
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
        "good": t.color("good"), "good_soft": t.color("good-soft"), "good_mark": t.color("good-mark"),
        "warn": t.color("warn"), "warn_soft": t.color("warn-soft"), "warn_mark": t.color("warn-mark"),
        "bad": t.color("bad"), "bad_soft": t.color("bad-soft"), "bad_mark": t.color("bad-mark"),
        # header band
        "header": t.color("header"),
        "header_ink": t.color("header-ink"),
        "header_edge": T.mix(t.color("header-ink"), t.color("header"), 0.16),
        "header_context": T.mix(t.color("header-ink"), t.color("header"), 0.66),
        "alarm_band": t.ramp("red", 600),
        "header_alarm_context": T.mix("#FFFFFF", t.ramp("red", 600), 0.78),
        # type
        "sans": sans_family(t),
        "mono": mono_family(t),
        "text": t.base_text_size,
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
        "s3_focus": t.space(3) - 1,
        "s4_focus": t.space(4) - 1,
        # radius
        "r_sm": t.radius("sm"), "r_md": t.radius("md"), "r_lg": t.radius("lg"),
        "pill_radius": 11,
        # metrics
        "control_inner": control_inner,
        # Rows carry no vertical padding, so this is the density's row height
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
# entry point
# ---------------------------------------------------------------------------

def apply(app=None, theme=T.LIGHT, density=T.COMFORTABLE):
    """Apply the system to *app*. Returns the resolved ``Tokens``.

    Safe to call again at runtime: a night-shift toggle costs one call.
    """
    global current

    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("theme.qt.apply() needs a QApplication")

    if not _fonts_loaded:
        load_fonts()

    current = T.load(theme=theme, density=density)
    icons.clear_cache()
    _family_cache.clear()
    _font_cache.clear()

    app.setStyle("Fusion")
    app.setPalette(build_palette(current))

    # The application font is what every widget inherits, now that the style
    # sheet no longer declares one globally.
    base = QFont(sans_family(current))
    base.setPixelSize(current.base_text_size)
    base.setWeight(QFont.Weight(400))
    app.setFont(base)

    app.setStyleSheet(build_stylesheet(current))
    return current


# ---------------------------------------------------------------------------
# property helpers
# ---------------------------------------------------------------------------

def _repolish(widget):
    """Qt does not restyle on a property change; make it."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


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


def tokens():
    """The live token table. Call it; do not bind ``current`` at import time."""
    return current


__all__ = [
    "apply", "tokens", "font", "mono_font", "style_header", "numeric_field_width",
    "sans_family", "mono_family",
    "set_variant", "set_role", "set_state", "set_invalid", "set_panel",
    "build_palette", "build_stylesheet", "load_fonts",
]
