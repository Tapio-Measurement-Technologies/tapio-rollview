from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QLabel, QListWidgetItem, QLineEdit, QPushButton, QComboBox, QMessageBox, QCheckBox, QSlider
from PySide6.QtGui import QDoubleValidator
from PySide6.QtCore import Signal, Slot, Qt
from utils import preferences
from utils.translation import _
from utils import profile_stats
from utils.excluded_regions import parse_excluded_regions
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
        self.apply_button.clicked.connect(self.save_settings)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    @Slot()
    def save_settings(self):
        selected_lang = list(self.languages.keys())[self.language_selector.currentIndex()]
        language_changed = selected_lang != self.initial_lang

        selected_distance_unit = list(self.distance_units.keys())[self.distance_unit_selector.currentIndex()]

        preferences.update_preferences({
            'locale': selected_lang,
            'distance_unit': selected_distance_unit
        })

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
        # Update limit values from UI inputs
        for setting in self.setting_widgets:
            setting.save_values()
        limits = [widget.limit for widget in self.setting_widgets]

        preferences.update_preferences({
            'alert_limits': limits
        })

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
    BAND_PASS_SLIDER_MIN = settings.BAND_PASS_HIGH_MIN
    BAND_PASS_SLIDER_MAX = 100
    BAND_PASS_SLIDER_STEP = 0.1
    BAND_PASS_SLIDER_SCALE = 10

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Band pass filter section
        band_pass_label = QLabel(_("BAND_PASS_FILTER"))
        layout.addWidget(band_pass_label)

        self.band_pass_slider_layout = QHBoxLayout()

        self.band_pass_slider = QSlider(Qt.Orientation.Horizontal)
        self.band_pass_slider.setMinimum(int(self.BAND_PASS_SLIDER_MIN * self.BAND_PASS_SLIDER_SCALE))
        self.band_pass_slider.setMaximum(int(self.BAND_PASS_SLIDER_MAX * self.BAND_PASS_SLIDER_SCALE))
        self.band_pass_slider.setSingleStep(1)
        band_pass_high = self._clamp_band_pass_high(float(getattr(preferences, "band_pass_high", 0) or 0))
        self.band_pass_slider.setValue(int(band_pass_high * self.BAND_PASS_SLIDER_SCALE))
        self.band_pass_slider.valueChanged.connect(self.on_band_pass_changed)
        self.band_pass_slider_layout.addWidget(self.band_pass_slider)

        self.band_pass_low_label = QLabel("0.0 -")
        self.band_pass_slider_layout.addWidget(self.band_pass_low_label)

        self.band_pass_high_input = QLineEdit()
        self.band_pass_high_input.setFixedWidth(55)
        self.band_pass_high_input.setValidator(QDoubleValidator(self.BAND_PASS_SLIDER_MIN, self.BAND_PASS_SLIDER_MAX, 1))
        self.band_pass_high_input.setText(f"{band_pass_high:.1f}")
        self.band_pass_high_input.editingFinished.connect(self.on_band_pass_input_changed)
        self.band_pass_slider_layout.addWidget(self.band_pass_high_input)

        self.band_pass_units_label = QLabel("cycles/m")
        self.band_pass_slider_layout.addWidget(self.band_pass_units_label)

        layout.addLayout(self.band_pass_slider_layout)

        # Y-axis override section
        y_override_label = QLabel("Override default Y limits")
        layout.addWidget(y_override_label)

        y_override_layout = QHBoxLayout()
        self.y_lim_low_label = QLabel(f"{_('MIN')}:")
        self.y_lim_low_input = QLineEdit()
        self.y_lim_low_input.setValidator(QDoubleValidator())
        self.y_lim_low_input.setPlaceholderText("auto")
        self.y_lim_low_input.setText(
            "" if preferences.y_lim_low_override is None else str(preferences.y_lim_low_override)
        )
        self.y_lim_low_input.textChanged.connect(self.enable_save_button)
        y_override_layout.addWidget(self.y_lim_low_label)
        y_override_layout.addWidget(self.y_lim_low_input)

        self.y_lim_high_label = QLabel(f"{_('MAX')}:")
        self.y_lim_high_input = QLineEdit()
        self.y_lim_high_input.setValidator(QDoubleValidator())
        self.y_lim_high_input.setPlaceholderText("auto")
        self.y_lim_high_input.setText(
            "" if preferences.y_lim_high_override is None else str(preferences.y_lim_high_override)
        )
        self.y_lim_high_input.textChanged.connect(self.enable_save_button)
        y_override_layout.addWidget(self.y_lim_high_label)
        y_override_layout.addWidget(self.y_lim_high_input)
        layout.addLayout(y_override_layout)

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

        # Excluded regions section
        self.excluded_regions_checkbox = QCheckBox(_("EXCLUDED_REGIONS_ENABLED"))
        self.excluded_regions_checkbox.setChecked(preferences.excluded_regions_enabled)
        self.excluded_regions_checkbox.stateChanged.connect(self.enable_save_button)
        self.excluded_regions_checkbox.stateChanged.connect(self.on_excluded_regions_enabled_changed)
        layout.addWidget(self.excluded_regions_checkbox)

        # Excluded regions input
        regions_layout = QHBoxLayout()
        self.excluded_regions_input = QLineEdit()
        self.excluded_regions_input.setText(preferences.excluded_regions)
        self.excluded_regions_input.setPlaceholderText("0-10,90-100")
        self.excluded_regions_input.textChanged.connect(self.enable_save_button)
        self.excluded_regions_input.returnPressed.connect(self.save_settings)
        self.excluded_regions_input.setEnabled(preferences.excluded_regions_enabled)

        self.excluded_regions_error = QLabel()
        self.excluded_regions_error.setStyleSheet("color: red; font-size: 12px;")
        self.excluded_regions_error.setVisible(False)

        regions_layout.addWidget(self.excluded_regions_input)
        layout.addLayout(regions_layout)
        layout.addWidget(self.excluded_regions_error)

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
    def on_excluded_regions_enabled_changed(self, state):
        """Enable/disable the excluded regions input based on checkbox state."""
        self.excluded_regions_input.setEnabled(state == Qt.CheckState.Checked.value)

    @Slot()
    def on_band_pass_changed(self, value):
        """Update band pass value input when slider moves."""
        high = value / self.BAND_PASS_SLIDER_SCALE
        self.band_pass_high_input.setText(f"{high:.1f}")
        self.enable_save_button()

    @Slot()
    def on_band_pass_input_changed(self):
        """Update slider when the user types in a cutoff value."""
        text = self.band_pass_high_input.text().strip()
        if not text:
            high = self.BAND_PASS_SLIDER_MIN
        else:
            try:
                high = self._clamp_band_pass_high(float(text))
            except ValueError:
                high = self.BAND_PASS_SLIDER_MIN

        self.band_pass_slider.setValue(int(round(high * self.BAND_PASS_SLIDER_SCALE)))
        self.band_pass_high_input.setText(f"{high:.1f}")
        self.enable_save_button()

    def _clamp_band_pass_high(self, value):
        return max(self.BAND_PASS_SLIDER_MIN, min(float(value), self.BAND_PASS_SLIDER_MAX))

    def _parse_optional_float(self, text):
        stripped = text.strip()
        return float(stripped) if stripped else None

    @Slot()
    def save_settings(self):
        # Validate excluded regions before saving
        regions_text = self.excluded_regions_input.text().strip()
        if regions_text:
            try:
                parse_excluded_regions(regions_text)
                self.excluded_regions_error.setVisible(False)
            except ValueError as e:
                self.excluded_regions_error.setText(str(e))
                self.excluded_regions_error.setVisible(True)
                return

        preferences.update_preferences({
            'show_spectrum': self.show_spectrum_checkbox.isChecked(),
            'continuous_mode': self.continuous_mode_checkbox.isChecked(),
            'flip_profiles': self.flip_profiles_checkbox.isChecked(),
            'excluded_regions_enabled': self.excluded_regions_checkbox.isChecked(),
            'excluded_regions': regions_text,
            'y_lim_low_override': self._parse_optional_float(self.y_lim_low_input.text()),
            'y_lim_high_override': self._parse_optional_float(self.y_lim_high_input.text()),
            'band_pass_low': 0,
            'band_pass_high': self._clamp_band_pass_high(self.band_pass_slider.value() / self.BAND_PASS_SLIDER_SCALE)
        })

        self.apply_button.setEnabled(False)
        self.settings_updated.emit()
