from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QLabel
from utils import preferences, profile_stats
from utils.translation import _


class AlertLimitEditor(QDialog):
    def __init__(self, stat_name, current_limit, parent=None):
        super().__init__(parent)
        self.stat_name = stat_name
        self.current_limit = current_limit or {'name': stat_name, 'min': None, 'max': None}

        self.setWindowTitle(f"Edit Alert Limits - {profile_stats.stat_labels.get(stat_name, stat_name)}")
        self.setModal(True)
        self.resize(300, 100)

        layout = QVBoxLayout()

        # Horizontal layout for min/max inputs
        inputs_layout = QHBoxLayout()

        self.min_edit = QLineEdit()
        self.max_edit = QLineEdit()

        # Set placeholder text and styling
        self.min_edit.setPlaceholderText(_("NOT_SET"))
        self.max_edit.setPlaceholderText(_("NOT_SET"))

        # Style placeholder text as grey
        placeholder_style = "QLineEdit { color: black; } QLineEdit::placeholder { color: grey; }"
        self.min_edit.setStyleSheet(placeholder_style)
        self.max_edit.setStyleSheet(placeholder_style)

        # Set current values
        if self.current_limit['min'] is not None:
            self.min_edit.setText(str(self.current_limit['min']))
        if self.current_limit['max'] is not None:
            self.max_edit.setText(str(self.current_limit['max']))

        # Add labels and inputs horizontally
        inputs_layout.addWidget(QLabel(f"{_('MIN')}:"))
        inputs_layout.addWidget(self.min_edit)
        inputs_layout.addWidget(QLabel(f"{_('MAX')}:"))
        inputs_layout.addWidget(self.max_edit)

        layout.addLayout(inputs_layout)

        # Error message label
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()  # Initially hidden
        layout.addWidget(self.error_label)

        # Buttons
        button_layout = QHBoxLayout()

        self.save_button = QPushButton(_("SAVE"))
        self.cancel_button = QPushButton(_("CANCEL"))
        self.clear_button = QPushButton(_("CLEAR"))

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

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def show_error(self, message):
        """Show error message in the dialog"""
        self.error_label.setText(message)
        self.error_label.show()

    def clear_error(self):
        """Clear any displayed error message"""
        self.error_label.hide()

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