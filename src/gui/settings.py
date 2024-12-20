from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QLabel, QListWidgetItem, QLineEdit, QPushButton
from PySide6.QtGui import QDoubleValidator
from PySide6.QtCore import Signal, Slot
from utils import preferences

class SettingsWindow(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settings")
        self.setGeometry(100, 100, 800, 400)

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        self.list_widget = QListWidget()
        main_layout.addWidget(self.list_widget)

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        self.alert_limit_page = AlertLimitSettingsPage()
        self.add_settings_page("Alert limits", self.alert_limit_page)

        self.list_widget.currentRowChanged.connect(self.display_page)
        self.list_widget.setCurrentRow(0)

    def add_settings_page(self, page_name, widget):
        widget.settings_updated.connect(self.settings_updated.emit)
        self.stacked_widget.addWidget(widget)
        item = QListWidgetItem(page_name)
        self.list_widget.addItem(item)

    def display_page(self, index):
        self.stacked_widget.setCurrentIndex(index)

class AlertLimitSettingsPage(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setting_widgets = []

        for limit in preferences.alert_limits:
            setting = AlertLimitSetting(limit)
            layout.addWidget(setting)
            self.setting_widgets.append(setting)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.addStretch()

        self.apply_button = QPushButton("Save", self)
        self.apply_button.setEnabled(False)  # Initially disabled
        self.apply_button.clicked.connect(self.save_alert_limits)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

        for setting in self.setting_widgets:
            setting.modified.connect(self.enable_save_button)

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    @Slot()
    def save_alert_limits(self):
        # Here you would add the code to save the alert limits
        for setting in self.setting_widgets:
            setting.save_values()
        limits = [ widget.limit for widget in self.setting_widgets ]
        preferences.update_alert_limits(limits)

        self.apply_button.setEnabled(False)
        self.settings_updated.emit()

class AlertLimitSetting(QWidget):
    modified = Signal()

    def __init__(self, limit):
        super().__init__()
        self.limit = limit
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.label = QLabel(f"{limit['label']} [{limit['units']}]")
        layout.addWidget(self.label)

        input_layout = QHBoxLayout()

        self.min_label = QLabel("Min:")
        self.min_input = QLineEdit()
        self.min_input.setValidator(QDoubleValidator())
        self.min_input.setText(str(limit['min']) if limit['min'] is not None else '')
        self.min_input.textChanged.connect(self.emit_modified)
        input_layout.addWidget(self.min_label)
        input_layout.addWidget(self.min_input)

        self.max_label = QLabel("Max:")
        self.max_input = QLineEdit()
        self.max_input.setValidator(QDoubleValidator())
        self.max_input.setText(str(limit['max']) if limit['max'] is not None else '')
        self.max_input.textChanged.connect(self.emit_modified)
        input_layout.addWidget(self.max_label)
        input_layout.addWidget(self.max_input)

        layout.addLayout(input_layout)

    @Slot()
    def emit_modified(self):
        self.modified.emit()

    def save_values(self):
        self.limit['min'] = float(self.min_input.text()) if self.min_input.text() else None
        self.limit['max'] = float(self.max_input.text()) if self.max_input.text() else None