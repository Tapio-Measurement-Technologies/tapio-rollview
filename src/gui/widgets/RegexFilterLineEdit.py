import re

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLineEdit

from theme import qt as theme_qt
from utils.translation import _


class RegexFilterLineEdit(QLineEdit):
    filter_changed = Signal(str, object)

    def __init__(self, placeholder_text="", debounce_ms=200, parent=None, guidance=""):
        super().__init__(parent)
        self._active_pattern = ""
        self._active_regex = None
        # What the field is for, said in the guidance row whenever the pattern
        # in it is valid. The error replaces it while it is not, and it comes
        # back when the pattern is fixed rather than leaving the field mute.
        self._base_guidance = guidance

        self.setStatusTip(guidance)
        self.setPlaceholderText(placeholder_text)
        self.setClearButtonEnabled(True)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(debounce_ms)
        self._debounce_timer.timeout.connect(self.apply_filter_text)
        self.textChanged.connect(self._schedule_filter_change)

    @property
    def active_pattern(self):
        return self._active_pattern

    @property
    def active_regex(self):
        return self._active_regex

    def _schedule_filter_change(self, text):
        self._debounce_timer.start()

    def apply_filter_text(self):
        pattern = self.text()
        if not pattern:
            compiled_regex = None
        else:
            try:
                compiled_regex = re.compile(pattern, re.IGNORECASE)
            except re.error as error:
                self._set_error(str(error))
                return

        self._set_error(None)
        if pattern == self._active_pattern:
            return

        self._active_pattern = pattern
        self._active_regex = compiled_regex
        self.filter_changed.emit(pattern, compiled_regex)

    def _set_error(self, error_text):
        theme_qt.set_invalid(self, bool(error_text))
        self.setStatusTip(
            _("REGEX_FILTER_INVALID_TOOLTIP").format(error=error_text)
            if error_text else self._base_guidance
        )
