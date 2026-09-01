from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
import theme
from theme import qt as theme_qt
from theme.guidance import set_guidance
from utils import preferences, profile_stats
from utils.translation import _


class AlertLimitEditor(QDialog):
    def __init__(self, stat_name, current_limit, parent=None):
        super().__init__(parent)
        self.stat_name = stat_name
        self.current_limit = current_limit or {'name': stat_name, 'min': None, 'max': None}

        self.setWindowTitle(
            f"{_('EDIT_ALERT_LIMITS')} - {profile_stats.stat_labels.get(stat_name, stat_name)}"
        )
        self.setModal(True)

        layout = QVBoxLayout()
        theme_qt.pad(layout, 3)
        theme_qt.gap(layout, 2)

        # Horizontal layout for min/max inputs
        inputs_layout = QHBoxLayout()
        theme_qt.gap(inputs_layout, 3)

        self.min_edit = QLineEdit()
        self.max_edit = QLineEdit()

        # A limit is a measured quantity, so both fields are mono and
        # right-aligned. The placeholder colour comes from the palette.
        self.min_edit.setPlaceholderText(_("NOT_SET"))
        self.max_edit.setPlaceholderText(_("NOT_SET"))
        # An empty field is a decision — no limit at that end — and the
        # placeholder says which state it is in, not what it means.
        set_guidance(self.min_edit, _("MIN"), _("GUIDANCE_LIMIT_FIELD"))
        set_guidance(self.max_edit, _("MAX"), _("GUIDANCE_LIMIT_FIELD"))
        for field in (self.min_edit, self.max_edit):
            theme_qt.set_property(field, "role", "data")
            field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Set current values
        if self.current_limit['min'] is not None:
            self.min_edit.setText(str(self.current_limit['min']))
        if self.current_limit['max'] is not None:
            self.max_edit.setText(str(self.current_limit['max']))

        # Labels sit above the field, always: a placeholder is not a label, it
        # disappears exactly when the operator needs it.
        inputs_layout.addWidget(self._field(_("MIN"), self.min_edit))
        inputs_layout.addWidget(self._field(_("MAX"), self.max_edit))

        layout.addLayout(inputs_layout)

        # Error message label
        # Never colour-only: the message says what is wrong, in words.
        self.error_label = QLabel()
        theme_qt.set_role(self.error_label, "hint")
        theme_qt.set_state(self.error_label, theme.STATUS_BAD)
        self.error_label.setWordWrap(True)
        self.error_label.hide()  # Initially hidden
        layout.addWidget(self.error_label)

        # Buttons
        button_layout = QHBoxLayout()

        # One primary: saving the limit is what this dialog exists for.
        self.save_button = QPushButton(_("SAVE"))
        theme_qt.set_variant(self.save_button, "primary")
        self.cancel_button = QPushButton(_("CANCEL"))
        self.clear_button = QPushButton(_("CLEAR"))
        theme_qt.set_variant(self.clear_button, "ghost")
        set_guidance(self.clear_button, _("CLEAR"), _("GUIDANCE_CLEAR_LIMITS"))

        # Set save as default button and connect Enter key
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        self.clear_button.setAutoDefault(False)
        self.cancel_button.setAutoDefault(False)

        self.save_button.clicked.connect(self.save_limits)
        self.cancel_button.clicked.connect(self.reject)
        self.clear_button.clicked.connect(self.clear_limits)

        # Connect Enter key on line edits to save
        self.min_edit.returnPressed.connect(self.save_limits)
        self.max_edit.returnPressed.connect(self.save_limits)

        # Clear errors when user starts typing
        self.min_edit.textChanged.connect(self.clear_error)
        self.max_edit.textChanged.connect(self.clear_error)

        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)

        # Two fields and a button row, and nothing that grows: any height
        # beyond what the content asks for is dead space, and a box layout
        # spends it by pulling the labels off their fields. The stretch gives
        # it somewhere harmless to go if the operator drags the window taller.
        layout.addStretch(1)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        # Width is a judgement — two numeric fields side by side — and height is
        # not: it is whatever the rows come to. Asking for a number here is how
        # the dialog ended up with 40 px of nothing in it.
        self.resize(360, self.sizeHint().height())

    def show_error(self, message):
        """Show error message in the dialog"""
        self.error_label.setText(message)
        self.error_label.show()

    def clear_error(self):
        """Clear any displayed error message"""
        self.error_label.hide()

    @staticmethod
    def _field(label_text, field):
        """A labelled numeric field: label above, value in mono below."""
        from PySide6.QtWidgets import QSizePolicy, QWidget

        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        holder_layout = QVBoxLayout(holder)
        theme_qt.pad(holder_layout, 0)
        theme_qt.gap(holder_layout, 1)
        label = QLabel(label_text)
        theme_qt.set_role(label, "label")
        holder_layout.addWidget(label)
        holder_layout.addWidget(field)
        return holder

    def save_limits(self):
        self.clear_error()  # Clear any previous errors

        try:
            # Parse values
            min_val = None
            max_val = None

            if self.min_edit.text().strip():
                min_val = float(self.min_edit.text())
            if self.max_edit.text().strip():
                max_val = float(self.max_edit.text())

            # Validate that min <= max if both are set
            if min_val is not None and max_val is not None and min_val > max_val:
                self.show_error(_("INVALID_ALERT_LIMIT_VALUES"))
                return

            # Update the limit in preferences
            updated_limits = []
            limit_found = False

            for limit in preferences.alert_limits:
                if limit['name'] == self.stat_name:
                    updated_limit = limit.copy()
                    updated_limit['min'] = min_val
                    updated_limit['max'] = max_val
                    updated_limits.append(updated_limit)
                    limit_found = True
                else:
                    updated_limits.append(limit)

            if not limit_found:
                # Create new limit entry if it doesn't exist
                updated_limits.append({
                    'name': self.stat_name,
                    'min': min_val,
                    'max': max_val
                })

            preferences.update_preferences({'alert_limits': updated_limits})
            self.accept()

        except ValueError:
            self.show_error(_("INVALID_ALERT_LIMIT_VALUES"))

    def clear_limits(self):
        self.min_edit.clear()
        self.max_edit.clear()
