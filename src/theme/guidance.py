# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""What the thing under the pointer is, said in one line at the foot of the window.

Written the same way everywhere, out of up to three parts:

* **title** — what the control is, in the words the interface already uses;
* **detail** — what it is holding right now: the limits on this tile, the
  folder that button opens, the reason that button is greyed out;
* **action** — what happens if you act on it.

They are joined into a single line, because the row that shows it is one line
high. Keep each part to a clause: the row is beside the work the window is
reporting, not a place to write a paragraph.

Guidance rather than a hover popup, deliberately. A tooltip waits for the
pointer to come to rest — the better part of a second on Qt's own timing — and
across a row of 120 px tiles an operator sweeping the pointer along them never
sees one and concludes there is nothing to find. A status tip goes out the
moment the pointer arrives, in a fixed place, and it never covers the thing it
is describing.

Three consequences worth knowing:

* Qt emits the status tip of the widget the pointer actually entered and does
  not look up the parent chain the way it does for tooltips. A composite whose
  children fill it — a tile with its labels — has to put the line on every part
  of itself, or the row goes quiet exactly where the pointer lands.
* Leaving one of those parts does not enter the composite around it, because
  the composite was never left. The part's Leave empties the row and no Enter
  follows it, so a tile answered over its labels and nowhere else on itself.
  The parts are made transparent to the mouse instead, which leaves the
  composite as the one thing the pointer enters and leaves.
* Item views read ``Qt.ItemDataRole.StatusTipRole`` from the model, so a row in
  a list or a tree answers in the same row of the window as everything else.

Nothing lives *only* here. The row is a convenience for whoever has a pointer;
every fact it states is also on a tile, in a column, or in a menu.
"""

#: Between the parts. A middle dot rather than an em dash: this is a list of
#: clauses in a cramped row, not a sentence with an aside in it.
SEPARATOR = " · "


def _detail_lines(detail):
    """*detail* as a list of non-empty strings, from a string or a sequence."""
    if detail is None:
        return []
    if isinstance(detail, str):
        return [detail] if detail else []
    return [str(line) for line in detail if line]


def compose(title=None, detail=None, action=None):
    """The guidance line for a title, its detail and an action.

    Every part is optional, and a call with nothing to say returns "" — which
    is what Qt reads as "no status tip", so a control whose detail has gone
    away stops claiming the row.
    """
    parts = []
    if title:
        parts.append(str(title))
    parts.extend(_detail_lines(detail))
    if action:
        parts.append(str(action))
    return SEPARATOR.join(parts)


def set_guidance(widget, title=None, detail=None, action=None):
    """Give *widget* a composed status tip. Returns the line, for the tests."""
    text = compose(title, detail, action)
    widget.setStatusTip(text)
    return text


def set_guidance_everywhere(widget, title=None, detail=None, action=None):
    """The same line on *widget* and on every widget inside it.

    For a composite the pointer never actually lands on: a stat tile is covered
    by its own labels, and Qt asks no parent for a status tip.

    The parts also hand the pointer through, so the composite is what the
    pointer enters wherever it arrives on it and the row stays filled all the
    way across. Parts that take the focus are left alone: those are controls
    rather than decoration, and a control that cannot be clicked is a worse
    fault than a row that goes quiet.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    text = compose(title, detail, action)
    widget.setStatusTip(text)
    for child in widget.findChildren(QWidget):
        child.setStatusTip(text)
        if child.focusPolicy() == Qt.FocusPolicy.NoFocus:
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return text
