from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QLabel, QListWidgetItem, QLineEdit, QPushButton, QComboBox, QMessageBox, QCheckBox
from PySide6.QtGui import QDoubleValidator
from PySide6.QtCore import Signal, Slot, Qt
from utils import preferences
from utils.translation import _
from utils import profile_stats
import settings

class SettingsWindow(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("WINDOW_TITLE_SETTINGS"))
        self.setGeometry(100, 100, 800, 400)

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        self.list_widget = QListWidget()
        main_layout.addWidget(self.list_widget)

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        self.general_settings_page = GeneralSettingsPage()
        self.add_settings_page(_("GENERAL_SETTINGS"), self.general_settings_page)

        self.alert_limit_page = AlertLimitSettingsPage()
        self.add_settings_page(_("ALERT_LIMITS"), self.alert_limit_page)

        self.advanced_settings_page = AdvancedSettingsPage()
        self.add_settings_page(_("ADVANCED_SETTINGS"), self.advanced_settings_page)

        self.list_widget.currentRowChanged.connect(self.display_page)
        self.list_widget.setCurrentRow(0)

    def add_settings_page(self, page_name, widget):
        widget.settings_updated.connect(self.settings_updated.emit)
        self.stacked_widget.addWidget(widget)
        item = QListWidgetItem(page_name)
        self.list_widget.addItem(item)

    def display_page(self, index):
        self.stacked_widget.setCurrentIndex(index)

class GeneralSettingsPage(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.language_label = QLabel(_("LANGUAGE"))
        layout.addWidget(self.language_label)

        self.language_selector = QComboBox()
        self.languages = {
            "en": "English",
            "ja": "日本語 (Japanese)"
        }

        current_locale = preferences.locale
        self.initial_lang = current_locale[:2] if current_locale else settings.LOCALE_DEFAULT

        self.language_selector.addItems(self.languages.values())

        for lang_code, lang_name in self.languages.items():
            if lang_code == self.initial_lang:
                self.language_selector.setCurrentText(lang_name)
                break

        self.language_selector.currentIndexChanged.connect(self.enable_save_button)
        layout.addWidget(self.language_selector)

        # Distance unit selector
        self.distance_unit_label = QLabel(_("DISTANCE_UNIT"))
        layout.addWidget(self.distance_unit_label)

        self.distance_unit_selector = QComboBox()
        self.distance_units = {code: unit.name for code, unit in settings.DISTANCE_UNITS.items()}

        current_distance_unit = preferences.distance_unit

        self.distance_unit_selector.addItems(self.distance_units.values())

        # Set current selection
        if current_distance_unit in self.distance_units:
            self.distance_unit_selector.setCurrentText(self.distance_units[current_distance_unit])

        self.distance_unit_selector.currentIndexChanged.connect(self.enable_save_button)
        layout.addWidget(self.distance_unit_selector)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.addStretch()

        self.apply_button = QPushButton(_("BUTTON_TEXT_SAVE"), self)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.save_language)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    @Slot()
    def save_language(self):
        selected_lang = list(self.languages.keys())[self.language_selector.currentIndex()]
        language_changed = selected_lang != self.initial_lang

        preferences.update_locale(selected_lang)

        selected_distance_unit = list(self.distance_units.keys())[self.distance_unit_selector.currentIndex()]
        preferences.update_distance_unit(selected_distance_unit)

        self.apply_button.setEnabled(False)
        self.settings_updated.emit()

        # Only show restart message if language was actually changed
        if language_changed:
            msgbox = QMessageBox()
            msgbox.setWindowTitle(_("RESTART_REQUIRED_MSGBOX_TITLE"))
            msgbox.setText(_("RESTART_REQUIRED_MSGBOX_TEXT"))
            msgbox.exec()

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

        self.apply_button = QPushButton(_("BUTTON_TEXT_SAVE"), self)
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

        self.label = QLabel(f"{profile_stats.stat_labels[limit['name']]} [{limit['units']}]")
        layout.addWidget(self.label)

        input_layout = QHBoxLayout()

        self.min_label = QLabel(f"{_("MIN")}:")
        self.min_input = QLineEdit()
        self.min_input.setValidator(QDoubleValidator())
        self.min_input.setText(str(limit['min']) if limit['min'] is not None else '')
        self.min_input.textChanged.connect(self.emit_modified)
        input_layout.addWidget(self.min_label)
        input_layout.addWidget(self.min_input)

        self.max_label = QLabel(f"{_("MAX")}:")
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

class AdvancedSettingsPage(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Show spectrum checkbox
        self.show_spectrum_checkbox = QCheckBox(_("SHOW_SPECTRUM"))
        self.show_spectrum_checkbox.setChecked(preferences.show_spectrum)
        self.show_spectrum_checkbox.stateChanged.connect(self.enable_save_button)
        layout.addWidget(self.show_spectrum_checkbox)

        # Continuous mode checkbox
        self.continuous_mode_checkbox = QCheckBox(_("CONTINUOUS_MODE"))
        self.continuous_mode_checkbox.setChecked(preferences.continuous_mode)
        self.continuous_mode_checkbox.stateChanged.connect(self.enable_save_button)
        layout.addWidget(self.continuous_mode_checkbox)

        # Flip profiles checkbox
        self.flip_profiles_checkbox = QCheckBox(_("FLIP_PROFILES"))
        self.flip_profiles_checkbox.setChecked(preferences.flip_profiles)
        self.flip_profiles_checkbox.stateChanged.connect(self.enable_save_button)
        layout.addWidget(self.flip_profiles_checkbox)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.addStretch()

        self.apply_button = QPushButton(_("BUTTON_TEXT_SAVE"), self)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.save_settings)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    @Slot()
    def save_settings(self):
        preferences.update_show_spectrum(self.show_spectrum_checkbox.isChecked())
        preferences.update_continuous_mode(self.continuous_mode_checkbox.isChecked())
        preferences.update_flip_profiles(self.flip_profiles_checkbox.isChecked())

        self.apply_button.setEnabled(False)
        self.settings_updated.emit()