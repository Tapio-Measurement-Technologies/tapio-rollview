# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The system's shared widgets.

One of them, now that the object bar is gone. The verdict on a run is told by
the stat tiles above the chart, where only the failing one turns red, and the
four status colours reach the rest of the interface through
``theme_qt.set_state`` and the status icons in ``theme.icons``.
"""

from PySide6.QtWidgets import QLabel

from theme import qt as theme_qt


class EyebrowLabel(QLabel):
    """The eyebrow: mono, 11 px, uppercase, muted.

    The mono face and the size come from the style sheet. The uppercasing is
    done to the string, because Qt style sheets have no ``text-transform`` and a
    ``QFont`` capitalisation does not survive the style sheet's polish. Doing it
    to the text is also the honest option for translations: ``str.upper()``
    leaves Japanese untouched, which is what should happen.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        theme_qt.set_role(self, "eyebrow")
        self.setText(text)

    def setText(self, text):
        super().setText((text or "").upper())
        self.setAccessibleName(text or "")


# The name this had while it was a font-only wrapper.
SectionLabel = EyebrowLabel
