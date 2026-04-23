from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QLabel, QListWidgetItem, QLineEdit, QPushButton, QComboBox, QMessageBox, QCheckBox, QSlider, QScrollArea, QFrame
from PySide6.QtGui import QDoubleValidator, QRegularExpressionValidator, QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import Signal, Slot, Qt, QLocale, QRegularExpression, QSignalBlocker
from utils import preferences
from utils.translation import _
from utils import profile_stats
from utils.excluded_regions import parse_excluded_regions
from utils.highlighted_regions import (
    AbsoluteMeanOffsetHardnessHighlightRegion,
    DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
    DISTANCE_HIGHLIGHT_MODE_RELATIVE,
    FixedHardnessHighlightRegion,
    HARDNESS_HIGHLIGHT_MODE_FIXED,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE,
    TABLEAU_COLORS,
    parse_distance_highlight_region,
    parse_hardness_highlight_region,
)
import settings

TABLEAU_COLOR_HEX = {
    "tab:blue": "#1f77b4",
    "tab:orange": "#ff7f0e",
    "tab:green": "#2ca02c",
    "tab:red": "#d62728",
    "tab:purple": "#9467bd",
    "tab:brown": "#8c564b",
    "tab:pink": "#e377c2",
    "tab:gray": "#7f7f7f",
    "tab:olive": "#bcbd22",
    "tab:cyan": "#17becf",
}


class SettingsWindow(QWidget):
    settings_updated = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("WINDOW_TITLE_SETTINGS"))
        self.setGeometry(100, 100, 800, 400)

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumWidth(180)
        self.list_widget.setMinimumWidth(150)
        main_layout.addWidget(self.list_widget)

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        self.general_settings_page = GeneralSettingsPage()
        self.add_settings_page(_("GENERAL_SETTINGS"), self.general_settings_page)

        self.alert_limit_page = AlertLimitSettingsPage()
        self.add_settings_page(_("ALERT_LIMITS"), self.alert_limit_page)

        self.distance_highlights_page = DistanceHighlightsSettingsPage()
        self.add_settings_page(_("DISTANCE_HIGHLIGHTS"), self.distance_highlights_page)

        self.hardness_highlights_page = HardnessHighlightsSettingsPage()
        self.add_settings_page(_("HARDNESS_HIGHLIGHTS"), self.hardness_highlights_page)

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
            "en": _("LANGUAGE_NAME_ENGLISH"),
            "ja": _("LANGUAGE_NAME_JAPANESE")
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
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(10)
        self.setting_widgets = []

        heading = QLabel(_("ALERT_LIMITS"))
        heading.setStyleSheet("font-weight: bold; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(heading)

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

class AlertLimitSetting(QFrame):
    modified = Signal()
    INPUT_WIDTH = 110

    def __init__(self, limit):
        super().__init__()
        self.limit = limit
        self.setObjectName("alertLimitCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#alertLimitCard {
                background-color: rgba(0, 0, 0, 0.03);
                border: 1px solid rgba(0, 0, 0, 0.12);
                border-radius: 4px;
            }
            """
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        self.setLayout(layout)

        self.label = QLabel(f"{profile_stats.stat_labels[limit['name']]} [{limit['units']}]")
        self.label.setMinimumWidth(120)
        layout.addWidget(self.label)

        layout.addStretch()

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.min_label = QLabel(f"{_("MIN")}:")
        self.min_input = QLineEdit()
        self.min_input.setMaximumWidth(self.INPUT_WIDTH)
        self.min_input.setValidator(QDoubleValidator())
        self.min_input.setText(str(limit['min']) if limit['min'] is not None else '')
        self.min_input.textChanged.connect(self.emit_modified)
        input_layout.addWidget(self.min_label)
        input_layout.addWidget(self.min_input)

        self.max_label = QLabel(f"{_("MAX")}:")
        self.max_input = QLineEdit()
        self.max_input.setMaximumWidth(self.INPUT_WIDTH)
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
        self.number_locale = QLocale.system()
        self.excluded_regions_modes = {
            settings.EXCLUDED_REGIONS_MODE_NONE: _("EXCLUDED_REGIONS_MODE_NONE"),
            settings.EXCLUDED_REGIONS_MODE_RELATIVE: _("EXCLUDED_REGIONS_MODE_RELATIVE"),
            settings.EXCLUDED_REGIONS_MODE_ABSOLUTE: _("EXCLUDED_REGIONS_MODE_ABSOLUTE"),
        }
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        filter_heading = self._create_section_heading(_("SECTION_HEADING_FILTERING"))
        layout.addWidget(filter_heading)

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
        # Dot-only numeric input with optional single decimal place (e.g. 2, 2.2, 100.0).
        band_pass_validator = QRegularExpressionValidator(
            QRegularExpression(r"^\d{0,3}(?:\.\d?)?$")
        )
        self.band_pass_high_input.setValidator(band_pass_validator)
        self.band_pass_high_input.setText(f"{band_pass_high:.1f}")
        self.band_pass_high_input.editingFinished.connect(self.on_band_pass_input_changed)
        self.band_pass_slider_layout.addWidget(self.band_pass_high_input)

        self.band_pass_units_label = QLabel(_("UNIT_CYCLES_PER_METER"))
        self.band_pass_slider_layout.addWidget(self.band_pass_units_label)

        layout.addLayout(self.band_pass_slider_layout)

        display_heading = self._create_section_heading(_("SECTION_HEADING_DISPLAY"))
        layout.addWidget(display_heading)

        # Y-axis scaling mode
        y_scaling_label = QLabel(_("DEFAULT_Y_AXIS_SCALING"))
        layout.addWidget(y_scaling_label)

        self.y_axis_scaling_selector = QComboBox()
        self.y_axis_scaling_modes = {
            settings.Y_AXIS_SCALING_START_AT_ZERO: _("Y_AXIS_SCALING_START_AT_ZERO"),
            settings.Y_AXIS_SCALING_FIT_TO_DATA: _("Y_AXIS_SCALING_FIT_TO_DATA")
        }
        self.y_axis_scaling_selector.addItems(self.y_axis_scaling_modes.values())
        current_scaling = getattr(preferences, "default_y_axis_scaling", settings.Y_AXIS_SCALING_DEFAULT)
        if current_scaling in self.y_axis_scaling_modes:
            self.y_axis_scaling_selector.setCurrentText(self.y_axis_scaling_modes[current_scaling])
        self.y_axis_scaling_selector.currentIndexChanged.connect(self.enable_save_button)
        layout.addWidget(self.y_axis_scaling_selector)

        # Y-axis override section
        y_override_label = QLabel(_("OVERRIDE_DEFAULT_Y_LIMITS"))
        layout.addWidget(y_override_label)

        y_override_layout = QHBoxLayout()
        self.y_lim_low_label = QLabel(f"{_('MIN')}:")
        self.y_lim_low_input = QLineEdit()
        y_lim_low_validator = QDoubleValidator()
        y_lim_low_validator.setLocale(self.number_locale)
        self.y_lim_low_input.setValidator(y_lim_low_validator)
        self.y_lim_low_input.setPlaceholderText(_("AUTO"))
        self.y_lim_low_input.setText(
            "" if preferences.y_lim_low_override is None else str(preferences.y_lim_low_override)
        )
        self.y_lim_low_input.textChanged.connect(self.enable_save_button)
        y_override_layout.addWidget(self.y_lim_low_label)
        y_override_layout.addWidget(self.y_lim_low_input)

        self.y_lim_high_label = QLabel(f"{_('MAX')}:")
        self.y_lim_high_input = QLineEdit()
        y_lim_high_validator = QDoubleValidator()
        y_lim_high_validator.setLocale(self.number_locale)
        self.y_lim_high_input.setValidator(y_lim_high_validator)
        self.y_lim_high_input.setPlaceholderText(_("AUTO"))
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

        profile_heading = self._create_section_heading(_("SECTION_HEADING_PROFILES"))
        layout.addWidget(profile_heading)

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

        excluded_regions_heading = self._create_section_heading(_("EXCLUDED_REGIONS_ENABLED"))
        layout.addWidget(excluded_regions_heading)

        # Excluded regions section
        excluded_regions_mode_layout = QHBoxLayout()
        self.excluded_regions_mode_label = QLabel(_("EXCLUDE_REGIONS_MODE"))
        self.excluded_regions_mode_label.setMinimumWidth(140)
        self.excluded_regions_mode_selector = QComboBox()
        self.excluded_regions_mode_selector.addItems(self.excluded_regions_modes.values())
        current_mode = getattr(preferences, "excluded_regions_mode", settings.EXCLUDED_REGIONS_MODE_DEFAULT)
        if current_mode in self.excluded_regions_modes:
            self.excluded_regions_mode_selector.setCurrentText(self.excluded_regions_modes[current_mode])
        self.excluded_regions_mode_selector.currentIndexChanged.connect(self.enable_save_button)
        self.excluded_regions_mode_selector.currentIndexChanged.connect(self.on_excluded_regions_mode_changed)
        excluded_regions_mode_layout.addWidget(self.excluded_regions_mode_label)
        excluded_regions_mode_layout.addWidget(self.excluded_regions_mode_selector)
        layout.addLayout(excluded_regions_mode_layout)

        # Excluded regions input
        regions_layout = QHBoxLayout()
        self.excluded_regions_label = QLabel(f"{_('EXCLUDED_REGIONS_ENABLED')}:")
        self.excluded_regions_label.setMinimumWidth(140)
        self.excluded_regions_input = QLineEdit()
        self.excluded_regions_input.setText(self._get_excluded_regions_display_text())
        self.excluded_regions_input.textChanged.connect(self.enable_save_button)
        self.excluded_regions_input.returnPressed.connect(self.save_settings)
        self.excluded_regions_input.setEnabled(current_mode != settings.EXCLUDED_REGIONS_MODE_NONE)

        self.excluded_regions_error = QLabel()
        self.excluded_regions_error.setStyleSheet("color: red; font-size: 12px;")
        self.excluded_regions_error.setVisible(False)

        regions_layout.addWidget(self.excluded_regions_label)
        regions_layout.addWidget(self.excluded_regions_input)
        layout.addLayout(regions_layout)
        layout.addWidget(self.excluded_regions_error)
        self._update_excluded_regions_ui()

        self.footer_layout = QHBoxLayout()
        self.footer_layout.addStretch()

        self.reset_defaults_button = QPushButton(_("RESET_DEFAULTS"), self)
        self.reset_defaults_button.clicked.connect(self.reset_to_defaults)
        self.footer_layout.addWidget(self.reset_defaults_button)

        self.apply_button = QPushButton(_("BUTTON_TEXT_SAVE"), self)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.save_settings)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    def _create_section_heading(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; margin-top: 8px; margin-bottom: 2px;")
        return label

    def _set_selector_value(self, selector, options_by_key, selected_key):
        if selected_key in options_by_key:
            selector.setCurrentText(options_by_key[selected_key])

    @Slot()
    def reset_to_defaults(self):
        blockers = [
            QSignalBlocker(self.band_pass_slider),
            QSignalBlocker(self.band_pass_high_input),
            QSignalBlocker(self.y_axis_scaling_selector),
            QSignalBlocker(self.y_lim_low_input),
            QSignalBlocker(self.y_lim_high_input),
            QSignalBlocker(self.show_spectrum_checkbox),
            QSignalBlocker(self.continuous_mode_checkbox),
            QSignalBlocker(self.flip_profiles_checkbox),
            QSignalBlocker(self.excluded_regions_mode_selector),
            QSignalBlocker(self.excluded_regions_input),
        ]

        default_band_pass_high = self._clamp_band_pass_high(settings.BAND_PASS_HIGH_DEFAULT)
        self.band_pass_slider.setValue(int(default_band_pass_high * self.BAND_PASS_SLIDER_SCALE))
        self.band_pass_high_input.setText(f"{default_band_pass_high:.1f}")
        self._set_selector_value(
            self.y_axis_scaling_selector,
            self.y_axis_scaling_modes,
            settings.Y_AXIS_SCALING_DEFAULT,
        )
        self.y_lim_low_input.setText("")
        self.y_lim_high_input.setText("")
        self.show_spectrum_checkbox.setChecked(settings.SHOW_SPECTRUM_DEFAULT)
        self.continuous_mode_checkbox.setChecked(settings.CONTINUOUS_MODE_DEFAULT)
        self.flip_profiles_checkbox.setChecked(settings.FLIP_PROFILES_DEFAULT)
        self._set_selector_value(
            self.excluded_regions_mode_selector,
            self.excluded_regions_modes,
            settings.EXCLUDED_REGIONS_MODE_DEFAULT,
        )
        self.excluded_regions_input.setText(settings.EXCLUDED_REGIONS_DEFAULT)
        self.excluded_regions_error.clear()
        self.excluded_regions_error.setVisible(False)
        self._update_excluded_regions_ui()
        self.enable_save_button()

    @Slot()
    def on_excluded_regions_mode_changed(self):
        """Update the UI when the excluded-region mode changes."""
        self.excluded_regions_error.setVisible(False)
        self._update_excluded_regions_ui()

    def _get_selected_excluded_regions_mode(self):
        return list(self.excluded_regions_modes.keys())[self.excluded_regions_mode_selector.currentIndex()]

    def _format_excluded_regions_ranges(self, ranges):
        return ",".join(f"{start:g}-{end:g}" for start, end in ranges)

    def _get_excluded_regions_display_text(self):
        return preferences.excluded_regions

    def _update_excluded_regions_ui(self):
        mode = self._get_selected_excluded_regions_mode()
        self.excluded_regions_input.setEnabled(mode != settings.EXCLUDED_REGIONS_MODE_NONE)
        if mode == settings.EXCLUDED_REGIONS_MODE_RELATIVE:
            self.excluded_regions_input.setPlaceholderText("0-10,90-100 (%)")
        elif mode == settings.EXCLUDED_REGIONS_MODE_ABSOLUTE:
            unit_info = preferences.get_distance_unit_info()
            self.excluded_regions_input.setPlaceholderText(f"0.1-0.5,9.0-10.0 ({unit_info.unit})")
        else:
            self.excluded_regions_input.setPlaceholderText("")

    def _serialize_excluded_regions(self, regions_text, mode):
        if not regions_text:
            return ""

        ranges = parse_excluded_regions(regions_text)
        return self._format_excluded_regions_ranges(ranges)

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

    def _parse_localized_float(self, text):
        value, ok = self.number_locale.toDouble(text.strip())
        if ok:
            return value

        # Fallback accepts the opposite separator when pasted from external sources.
        normalized = text.strip().replace(",", ".")
        try:
            return float(normalized)
        except ValueError as exc:
            raise ValueError("Invalid numeric value") from exc

    def _parse_optional_float(self, text):
        stripped = text.strip()
        return self._parse_localized_float(stripped) if stripped else None

    @Slot()
    def save_settings(self):
        # Validate excluded regions before saving
        regions_text = self.excluded_regions_input.text().strip()
        excluded_regions_mode = self._get_selected_excluded_regions_mode()
        stored_regions_text = regions_text
        if regions_text and excluded_regions_mode != settings.EXCLUDED_REGIONS_MODE_NONE:
            try:
                parse_excluded_regions(regions_text)
                self.excluded_regions_error.setVisible(False)
                stored_regions_text = self._serialize_excluded_regions(regions_text, excluded_regions_mode)
            except ValueError as e:
                self.excluded_regions_error.setText(str(e))
                self.excluded_regions_error.setVisible(True)
                return

        preferences.update_preferences({
            'show_spectrum': self.show_spectrum_checkbox.isChecked(),
            'continuous_mode': self.continuous_mode_checkbox.isChecked(),
            'flip_profiles': self.flip_profiles_checkbox.isChecked(),
            'excluded_regions_enabled': excluded_regions_mode != settings.EXCLUDED_REGIONS_MODE_NONE,
            'excluded_regions_mode': excluded_regions_mode,
            'excluded_regions': stored_regions_text,
            'y_lim_low_override': self._parse_optional_float(self.y_lim_low_input.text()),
            'y_lim_high_override': self._parse_optional_float(self.y_lim_high_input.text()),
            'default_y_axis_scaling': list(self.y_axis_scaling_modes.keys())[self.y_axis_scaling_selector.currentIndex()],
            'band_pass_low': 0,
            'band_pass_high': self._clamp_band_pass_high(self.band_pass_slider.value() / self.BAND_PASS_SLIDER_SCALE)
        })

        self.apply_button.setEnabled(False)
        self.settings_updated.emit()


class HighlightRegionRowBase(QFrame):
    modified = Signal()
    remove_requested = Signal(QWidget)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_labels = {
            "tab:blue": _("COLOR_BLUE"),
            "tab:orange": _("COLOR_ORANGE"),
            "tab:green": _("COLOR_GREEN"),
            "tab:red": _("COLOR_RED"),
            "tab:purple": _("COLOR_PURPLE"),
            "tab:brown": _("COLOR_BROWN"),
            "tab:pink": _("COLOR_PINK"),
            "tab:gray": _("COLOR_GRAY"),
            "tab:olive": _("COLOR_OLIVE"),
            "tab:cyan": _("COLOR_CYAN"),
        }

        self.setObjectName("highlightedRegionRow")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#highlightedRegionRow {
                background-color: rgba(0, 0, 0, 0.03);
                border: 1px solid rgba(0, 0, 0, 0.12);
                border-radius: 4px;
            }
            """
        )

    def _create_card_layout(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.setLayout(layout)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        layout.addLayout(top_row)
        return top_row

    def _create_field_group(self, parent_layout):
        field_layout = QVBoxLayout()
        field_layout.setSpacing(4)
        field_layout.setContentsMargins(0, 0, 0, 0)
        parent_layout.addLayout(field_layout)
        return field_layout

    def _populate_color_selector(self):
        for color, label in self.color_labels.items():
            self.color_selector.addItem(self._create_color_icon(color), label)

    def _create_color_icon(self, color_name):
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TABLEAU_COLOR_HEX[color_name]))
        painter.drawEllipse(1, 1, 14, 14)
        painter.end()

        return QIcon(pixmap)

    def _get_selected_color(self):
        return list(self.color_labels.keys())[self.color_selector.currentIndex()]

    def _add_color_and_remove(self, top_row, spacer_label):
        color_group = self._create_field_group(top_row)
        self.color_label = QLabel(_("COLOR"))
        color_group.addWidget(self.color_label)
        self.color_selector = QComboBox()
        self._populate_color_selector()
        self.color_selector.currentIndexChanged.connect(lambda _index: self.modified.emit())
        self.color_selector.setMaximumWidth(130)
        self.color_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        color_group.addWidget(self.color_selector)

        top_row.addStretch()

        remove_group = self._create_field_group(top_row)
        self.remove_label_spacer = QLabel("")
        self.remove_label_spacer.setFixedHeight(spacer_label.sizeHint().height())
        remove_group.addWidget(self.remove_label_spacer)

        self.remove_button = QPushButton(_("REMOVE"))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        self.remove_button.setMaximumWidth(90)
        remove_group.addWidget(self.remove_button)


class DistanceHighlightRow(HighlightRegionRowBase):
    def __init__(self, region=None, parent=None):
        super().__init__(parent)
        self.modes = {
            DISTANCE_HIGHLIGHT_MODE_RELATIVE: _("ANNOTATION_MODE_RELATIVE"),
            DISTANCE_HIGHLIGHT_MODE_ABSOLUTE: _("ANNOTATION_MODE_ABSOLUTE"),
        }

        top_row = self._create_card_layout()

        range_group = self._create_field_group(top_row)
        self.range_label = QLabel(_("RANGE"))
        range_group.addWidget(self.range_label)

        range_inputs = QHBoxLayout()
        range_inputs.setSpacing(6)
        range_group.addLayout(range_inputs)
        self.start_input = QLineEdit()
        self.start_input.setMinimumWidth(48)
        self.start_input.setMaximumWidth(60)
        self.start_input.textChanged.connect(lambda _text: self.modified.emit())
        range_inputs.addWidget(self.start_input)

        self.range_separator = QLabel("–")
        range_inputs.addWidget(self.range_separator)

        self.end_input = QLineEdit()
        self.end_input.setMinimumWidth(48)
        self.end_input.setMaximumWidth(60)
        self.end_input.textChanged.connect(lambda _text: self.modified.emit())
        range_inputs.addWidget(self.end_input)

        mode_group = self._create_field_group(top_row)
        self.mode_label = QLabel(_("MODE"))
        mode_group.addWidget(self.mode_label)
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(self.modes.values())
        self.mode_selector.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_selector.currentIndexChanged.connect(lambda _index: self.modified.emit())
        self.mode_selector.setMaximumWidth(150)
        self.mode_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        mode_group.addWidget(self.mode_selector)

        self._add_color_and_remove(top_row, self.range_label)
        self._set_region(region)
        self._update_placeholders()

    def _set_region(self, region):
        if region is None:
            self.start_input.clear()
            self.end_input.clear()
            self.mode_selector.setCurrentText(self.modes[DISTANCE_HIGHLIGHT_MODE_RELATIVE])
            self.color_selector.setCurrentText(self.color_labels[TABLEAU_COLORS[0]])
            return

        self.start_input.setText("" if region.start == float("-inf") else f"{region.start:g}")
        self.end_input.setText("" if region.end == float("inf") else f"{region.end:g}")
        self.mode_selector.setCurrentText(self.modes[region.mode])
        self.color_selector.setCurrentText(self.color_labels[region.color])

    def _get_selected_mode(self):
        return list(self.modes.keys())[self.mode_selector.currentIndex()]

    def _update_placeholders(self):
        self.start_input.setPlaceholderText(_("MIN"))
        self.end_input.setPlaceholderText(_("MAX"))

    @Slot()
    def _on_mode_changed(self):
        self._update_placeholders()

    def is_empty(self):
        return not self.start_input.text().strip() and not self.end_input.text().strip()

    def to_region(self):
        return parse_distance_highlight_region(
            self.start_input.text(),
            self.end_input.text(),
            self._get_selected_mode(),
            self._get_selected_color(),
        )


class HardnessHighlightRow(HighlightRegionRowBase):
    def __init__(self, region=None, parent=None):
        super().__init__(parent)
        self.modes = {
            HARDNESS_HIGHLIGHT_MODE_FIXED: _("HARDNESS_HIGHLIGHT_MODE_FIXED"),
            HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE: _("HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE"),
            HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE: _("HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE"),
        }

        top_row = self._create_card_layout()

        range_group = self._create_field_group(top_row)
        self.range_label = QLabel(_("RANGE"))
        range_group.addWidget(self.range_label)

        range_inputs = QHBoxLayout()
        range_inputs.setSpacing(6)
        range_group.addLayout(range_inputs)
        self.first_input = QLineEdit()
        self.first_input.setMinimumWidth(56)
        self.first_input.setMaximumWidth(60)
        self.first_input.textChanged.connect(lambda _text: self.modified.emit())
        range_inputs.addWidget(self.first_input)

        self.range_separator = QLabel("–")
        range_inputs.addWidget(self.range_separator)

        self.second_input = QLineEdit()
        self.second_input.setMinimumWidth(56)
        self.second_input.setMaximumWidth(60)
        self.second_input.textChanged.connect(lambda _text: self.modified.emit())
        range_inputs.addWidget(self.second_input)

        mode_group = self._create_field_group(top_row)
        self.mode_label = QLabel(_("MODE"))
        mode_group.addWidget(self.mode_label)
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(self.modes.values())
        self.mode_selector.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_selector.currentIndexChanged.connect(lambda _index: self.modified.emit())
        self.mode_selector.setMaximumWidth(200)
        self.mode_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        mode_group.addWidget(self.mode_selector)

        self._add_color_and_remove(top_row, self.range_label)
        self._set_region(region)
        self._update_labels()

    def _set_region(self, region):
        if region is None:
            self.first_input.clear()
            self.second_input.clear()
            self.mode_selector.setCurrentText(self.modes[HARDNESS_HIGHLIGHT_MODE_FIXED])
            self.color_selector.setCurrentText(self.color_labels[TABLEAU_COLORS[0]])
            return

        self.mode_selector.setCurrentText(self.modes[region.mode])
        self.color_selector.setCurrentText(self.color_labels[region.color])
        if isinstance(region, FixedHardnessHighlightRegion):
            self.first_input.setText("" if region.min_value is None else f"{region.min_value:g}")
            self.second_input.setText("" if region.max_value is None else f"{region.max_value:g}")
        elif isinstance(region, AbsoluteMeanOffsetHardnessHighlightRegion):
            self.first_input.setText("" if region.lower_offset is None else f"{region.lower_offset:g}")
            self.second_input.setText("" if region.upper_offset is None else f"{region.upper_offset:g}")
        else:
            self.first_input.setText("" if region.lower_percent is None else f"{region.lower_percent:g}")
            self.second_input.setText("" if region.upper_percent is None else f"{region.upper_percent:g}")

    def _get_selected_mode(self):
        return list(self.modes.keys())[self.mode_selector.currentIndex()]

    def _update_labels(self):
        mode = self._get_selected_mode()
        if mode == HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_RELATIVE:
            self.first_input.setPlaceholderText(_("LOWER") + " %")
            self.second_input.setPlaceholderText(_("UPPER") + " %")
        else:
            self.first_input.setPlaceholderText(_("LOWER"))
            self.second_input.setPlaceholderText(_("UPPER"))

    @Slot()
    def _on_mode_changed(self):
        self._update_labels()

    def is_empty(self):
        return not self.first_input.text().strip() and not self.second_input.text().strip()

    def to_region(self):
        return parse_hardness_highlight_region(
            self.first_input.text(),
            self.second_input.text(),
            self._get_selected_mode(),
            self._get_selected_color(),
        )


class HighlightRegionsSettingsPageBase(QWidget):
    settings_updated = Signal()

    def __init__(self, title_key, description_key, add_button_key, row_factory, preference_key, defaults_value, empty_title_key, empty_help_key):
        super().__init__()
        self.rows = []
        self.row_factory = row_factory
        self.preference_key = preference_key
        self.defaults_value = defaults_value

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel(_(title_key))
        heading.setStyleSheet("font-weight: bold; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(heading)

        description = QLabel(_(description_key))
        description.setWordWrap(True)
        layout.addWidget(description)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_layout.setSpacing(10)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_container.setLayout(self.rows_layout)

        self.empty_state_card = self._create_empty_state_card(empty_title_key, empty_help_key)
        self.rows_layout.addWidget(self.empty_state_card)

        self.rows_scroll_area = QScrollArea()
        self.rows_scroll_area.setWidgetResizable(True)
        self.rows_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.rows_scroll_area.setWidget(self.rows_container)
        self.rows_scroll_area.setMinimumHeight(220)
        layout.addWidget(self.rows_scroll_area)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red; font-size: 12px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        controls_layout = QHBoxLayout()
        self.add_button = QPushButton(_(add_button_key))
        self.add_button.clicked.connect(self.add_empty_row)
        controls_layout.addWidget(self.add_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.addStretch()

        self.reset_defaults_button = QPushButton(_("RESET_DEFAULTS"), self)
        self.reset_defaults_button.clicked.connect(self.reset_to_defaults)
        self.footer_layout.addWidget(self.reset_defaults_button)

        self.apply_button = QPushButton(_("BUTTON_TEXT_SAVE"), self)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.save_settings)
        self.footer_layout.addWidget(self.apply_button)

        layout.addLayout(self.footer_layout)

        self._load_regions(getattr(preferences, self.preference_key))

    def _create_empty_state_card(self, title_key, help_key):
        card = QFrame()
        card.setObjectName("annotationEmptyStateCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            """
            QFrame#annotationEmptyStateCard {
                background-color: rgba(0, 0, 0, 0.02);
                border: 1px dashed rgba(0, 0, 0, 0.18);
                border-radius: 4px;
            }
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)
        card.setLayout(layout)

        title = QLabel(_(title_key))
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        description = QLabel(_(help_key))
        description.setWordWrap(True)
        layout.addWidget(description)
        return card

    def _update_empty_state(self):
        self.empty_state_card.setVisible(len(self.rows) == 0)

    def _connect_row(self, row):
        row.modified.connect(self.enable_save_button)
        row.modified.connect(self._hide_error)
        row.remove_requested.connect(self.remove_row)

    def _load_regions(self, regions):
        for row in list(self.rows):
            self.remove_row(row, enable_save=False)

        for region in regions:
            self._add_row(region=region, enable_save=False)

        self._update_empty_state()

    def _add_row(self, region=None, enable_save=True):
        row = self.row_factory(region=region)
        self._connect_row(row)
        if hasattr(row, "start_input"):
            row.start_input.returnPressed.connect(self.save_settings)
            row.end_input.returnPressed.connect(self.save_settings)
        else:
            row.first_input.returnPressed.connect(self.save_settings)
            row.second_input.returnPressed.connect(self.save_settings)

        self.rows.append(row)
        self.rows_layout.addWidget(row)
        self._update_empty_state()
        if enable_save:
            self.enable_save_button()
        return row

    @Slot()
    def add_empty_row(self):
        self._add_row()

    @Slot()
    def enable_save_button(self):
        self.apply_button.setEnabled(True)

    @Slot()
    def _hide_error(self):
        self.error_label.setVisible(False)

    @Slot(QWidget)
    def remove_row(self, row, enable_save=True):
        if row not in self.rows:
            return

        self.rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self._update_empty_state()
        self._hide_error()
        if enable_save:
            self.enable_save_button()

    def _collect_regions(self):
        regions = []
        for index, row in enumerate(self.rows, start=1):
            if row.is_empty():
                continue
            try:
                region = row.to_region()
            except ValueError as exc:
                raise ValueError(f"Row {index}: {exc}") from exc
            if region is not None:
                regions.append(region)
        return regions

    @Slot()
    def reset_to_defaults(self):
        self._load_regions(self.defaults_value)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.enable_save_button()

    @Slot()
    def save_settings(self):
        try:
            regions = self._collect_regions()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return

        preferences.update_preferences({
            self.preference_key: regions,
        })
        self.apply_button.setEnabled(False)
        self.error_label.setVisible(False)
        self.settings_updated.emit()


class DistanceHighlightsSettingsPage(HighlightRegionsSettingsPageBase):
    def __init__(self):
        super().__init__(
            title_key="DISTANCE_HIGHLIGHTS",
            description_key="DISTANCE_HIGHLIGHTS_HELP",
            add_button_key="ADD_DISTANCE_HIGHLIGHT",
            row_factory=DistanceHighlightRow,
            preference_key="distance_highlight_regions",
            defaults_value=settings.DISTANCE_HIGHLIGHT_REGIONS_DEFAULT,
            empty_title_key="DISTANCE_HIGHLIGHTS_EMPTY_TITLE",
            empty_help_key="DISTANCE_HIGHLIGHTS_EMPTY_HELP",
        )


class HardnessHighlightsSettingsPage(HighlightRegionsSettingsPageBase):
    def __init__(self):
        super().__init__(
            title_key="HARDNESS_HIGHLIGHTS",
            description_key="HARDNESS_HIGHLIGHTS_HELP",
            add_button_key="ADD_HARDNESS_HIGHLIGHT",
            row_factory=HardnessHighlightRow,
            preference_key="hardness_highlight_regions",
            defaults_value=settings.HARDNESS_HIGHLIGHT_REGIONS_DEFAULT,
            empty_title_key="HARDNESS_HIGHLIGHTS_EMPTY_TITLE",
            empty_help_key="HARDNESS_HIGHLIGHTS_EMPTY_HELP",
        )
