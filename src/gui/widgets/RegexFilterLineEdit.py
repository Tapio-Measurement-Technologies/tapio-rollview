import re

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLineEdit

from utils.translation import _


class RegexFilterLineEdit(QLineEdit):
    filter_changed = Signal(str, object)

    def __init__(self, placeholder_text="", debounce_ms=200, parent=None):
        super().__init__(parent)
        self._active_pattern = ""
        self._active_regex = None

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
        if error_text:
            self.setStyleSheet(
                "QLineEdit { border: 1px solid #c0392b; background-color: #fff6f6; }"
            )
            self.setToolTip(_("REGEX_FILTER_INVALID_TOOLTIP").format(error=error_text))
            return

        self.setStyleSheet("")
        self.setToolTip("")
