# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The system's shared components, as Qt widgets.

Three of them, because these are the three RollView was hand-rolling:

``StatusPill``    the four states, each with an icon *and* a word
``AppHeader``     the object bar — the roll, not the app
``EyebrowLabel``  the eyebrow

Colour never carries a meaning by itself here. A pill without its icon and its
label is not a pill.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from theme import icons
from theme import qt as theme_qt
from theme import tokens as T

# The only four states. A fifth "informational blue" does not exist — that is
# what ordinary text is for.
STATES = (T.STATUS_GOOD, T.STATUS_WARN, T.STATUS_BAD, T.STATUS_IDLE)


class StatusPill(QLabel):
    """Icon + colour + label. Never colour alone.

    ``good``  every statistic is inside its configured limits
    ``warn``  inside limits, but within the warning band; nothing has failed
    ``bad``   a limit was exceeded — the only meaning red ever has
    ``idle``  no verdict yet: measuring, syncing, or no limits configured

    The icon rides inside the label as an inline image so it stays on the text
    baseline at any font size and the whole pill is one styled box.
    """

    ICON_SIZE = 12

    def __init__(self, state=T.STATUS_IDLE, text="", parent=None):
        super().__init__(parent)
        self.setObjectName("statusPill")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._state = None
        self._text = text
        self.set_status(state, text)

    def set_status(self, state, text=None):
        if state not in STATES:
            state = T.STATUS_IDLE
        if text is not None:
            self._text = text
        self._state = state

        tokens = theme_qt.tokens()
        path = icons.write_png(state, self.ICON_SIZE, tokens.status_ink(state))
        self.setText(
            f'<img src="{path}" width="{self.ICON_SIZE}" height="{self.ICON_SIZE}">'
            f'&nbsp;&nbsp;{self._text}'
        )
        theme_qt.set_property(self, "pill", state)
        # Screen readers and the QA checklist both want the word, not the colour.
        self.setAccessibleName(self._text)

    def state(self):
        return self._state

    def status_text(self):
        return self._text


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


class AppHeader(QWidget):
    """The object bar.

    The sample or roll ID is the most useful thing in the window, so it lives in
    the header at all times — the title bar states the object, not the app.

    When a limit is exceeded the whole band goes red rather than a label inside
    it: an alarm has to be readable as a failure from across a room, without
    reading a word of it.
    """

    def __init__(self, app_name, parent=None):
        super().__init__(parent)
        self.setObjectName("appHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        tokens = theme_qt.tokens()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.space(2), tokens.space(1),
                                  tokens.space(2), tokens.space(1))
        layout.setSpacing(tokens.space(2))

        self.mark = QLabel()
        self.mark.setFixedSize(18, 18)
        layout.addWidget(self.mark)

        self.name = QLabel(app_name)
        theme_qt.set_property(self.name, "role", "appName")
        layout.addWidget(self.name)

        # Mono and muted; the style sheet owns both, keyed off role="context".
        self.context = QLabel()
        theme_qt.set_property(self.context, "role", "context")
        layout.addWidget(self.context)

        layout.addStretch(1)

        self.pill = StatusPill(T.STATUS_IDLE, "")
        self.pill.setVisible(False)
        layout.addWidget(self.pill)

        self._refresh_mark()

    def _refresh_mark(self):
        """The logo square — the one place inside the app red is decorative.

        It is the identity mark, not a status; the red rule carves it out
        explicitly.
        """
        tokens = theme_qt.tokens()
        red = tokens.ramp("red", 600)
        self.mark.setPixmap(icons.pixmap("measure", 18, "#FFFFFF", stroke=2.0))
        self.mark.setStyleSheet(
            f"background-color: {red}; border-radius: {tokens.radius('sm')}px;"
        )

    def refresh(self):
        """Repaint what a style sheet cannot reach, after a theme change."""
        self._refresh_mark()
        if self.pill.isVisible():
            self.pill.set_status(self.pill.state())

    def set_context(self, text):
        """The roll, the sample, the profile count — whatever names the object."""
        self.context.setText(text or "")

    def set_status(self, state, text):
        """Raise or clear the alarm band."""
        if state is None:
            self.pill.setVisible(False)
            theme_qt.set_property(self, "state", "")
            return
        self.pill.set_status(state, text)
        self.pill.setVisible(True)
        theme_qt.set_property(self, "state", "bad" if state == T.STATUS_BAD else "")
        for child in (self.name, self.context):
            child.style().unpolish(child)
            child.style().polish(child)
