from dataclasses import dataclass
import copy
import json
import os

from PySide6.QtCore import QDir

import settings
from utils.highlighted_regions import (
    normalize_distance_highlight_regions,
    normalize_hardness_highlight_regions,
    serialize_distance_highlight_regions,
    serialize_hardness_highlight_regions,
)

default_preferences_file_path = QDir(QDir.homePath()).filePath(settings.PREFERENCES_FILE_PATH)
preferences_file_path = default_preferences_file_path


@dataclass(frozen=True)
class LoadPreferencesResult:
    status: str
    path: str
    error: str | None = None


LOAD_STATUS_LOADED = "loaded"
LOAD_STATUS_CREATED_DEFAULTS = "created_defaults"
LOAD_STATUS_EMPTY = "empty"
LOAD_STATUS_INVALID = "invalid"


# Default values with type converters for special handling
_DEFAULTS = {
    'alert_limits': settings.ALERT_LIMITS_DEFAULT,
    'enabled_postprocessors': settings.DEFAULT_ENABLED_POSTPROCESSORS,
    'show_all_com_ports': settings.SHOW_ALL_COM_PORTS_DEFAULT,
    'show_plot_toolbar': settings.SHOW_PLOT_TOOLBAR_DEFAULT,
    'recalculate_mean': settings.RECALCULATE_MEAN_DEFAULT,
    'locale': settings.LOCALE_DEFAULT,
    'pinned_serial_ports': settings.PINNED_SERIAL_PORTS_DEFAULT,
    'distance_unit': settings.DISTANCE_UNIT_DEFAULT,
    'continuous_mode': settings.CONTINUOUS_MODE_DEFAULT,
    'show_spectrum': settings.SHOW_SPECTRUM_DEFAULT,
    'flip_profiles': settings.FLIP_PROFILES_DEFAULT,
    'excluded_regions_enabled': settings.EXCLUDED_REGIONS_ENABLED_DEFAULT,
    'excluded_regions': settings.EXCLUDED_REGIONS_DEFAULT,
    'excluded_regions_mode': settings.EXCLUDED_REGIONS_MODE_DEFAULT,
    'distance_highlight_regions': settings.DISTANCE_HIGHLIGHT_REGIONS_DEFAULT,
    'hardness_highlight_regions': settings.HARDNESS_HIGHLIGHT_REGIONS_DEFAULT,
    'y_lim_low_override': settings.Y_LIM_LOW_OVERRIDE_DEFAULT,
    'y_lim_high_override': settings.Y_LIM_HIGH_OVERRIDE_DEFAULT,
    'default_y_axis_scaling': settings.Y_AXIS_SCALING_DEFAULT,
    'band_pass_low': settings.BAND_PASS_LOW_DEFAULT,
    'band_pass_high': settings.BAND_PASS_HIGH_DEFAULT,
}

# Type converters for loading from JSON (for special types like sets)
_LOADERS = {
    'pinned_serial_ports': set,
    'distance_highlight_regions': normalize_distance_highlight_regions,
    'hardness_highlight_regions': normalize_hardness_highlight_regions,
}

# Type converters for saving to JSON (for special types like sets)
_SAVERS = {
    'pinned_serial_ports': list,
    'distance_highlight_regions': serialize_distance_highlight_regions,
    'hardness_highlight_regions': serialize_hardness_highlight_regions,
}


def _default_value(key):
    return copy.deepcopy(_DEFAULTS[key])


def _normalize_alert_limits(limits):
    if not isinstance(limits, list):
        limits = []

    normalized_limits = []
    configured_by_name = {
        limit.get('name'): limit
        for limit in limits
        if isinstance(limit, dict) and limit.get('name')
    }

    for default_limit in settings.ALERT_LIMITS_DEFAULT:
        existing_limit = configured_by_name.pop(default_limit['name'], {})
        normalized_limit = copy.deepcopy(default_limit)
        normalized_limit['units'] = existing_limit.get('units', normalized_limit['units'])
        normalized_limit['min'] = existing_limit.get('min')
        normalized_limit['max'] = existing_limit.get('max')
        normalized_limits.append(normalized_limit)

    for extra_limit in configured_by_name.values():
        preserved_limit = copy.deepcopy(extra_limit)
        preserved_limit.setdefault('units', '')
        preserved_limit.setdefault('min', None)
        preserved_limit.setdefault('max', None)
        normalized_limits.append(preserved_limit)

    return normalized_limits


def _serialized_preferences():
    serialized = {}
    for key in _DEFAULTS.keys():
        value = globals()[key]
        if key in _SAVERS:
            value = _SAVERS[key](value)
        serialized[key] = value
    return serialized


def _reset_preferences_to_defaults():
    for key in _DEFAULTS.keys():
        value = _default_value(key)
        if key == 'alert_limits':
            value = _normalize_alert_limits(value)
        elif key == 'distance_highlight_regions':
            value = normalize_distance_highlight_regions(value)
        elif key == 'hardness_highlight_regions':
            value = normalize_hardness_highlight_regions(value)
        globals()[key] = value


def _apply_loaded_preferences(loaded_prefs):
    if not isinstance(loaded_prefs, dict):
        raise ValueError("Top-level JSON must be an object")

    _reset_preferences_to_defaults()

    for key in _DEFAULTS.keys():
        if key not in loaded_prefs:
            continue

        value = loaded_prefs[key]
        if key in _LOADERS:
            value = _LOADERS[key](value)
        elif key == 'alert_limits':
            value = _normalize_alert_limits(value)
        globals()[key] = value

    if 'excluded_regions_mode' not in loaded_prefs:
        globals()['excluded_regions_mode'] = (
            settings.EXCLUDED_REGIONS_MODE_RELATIVE
            if loaded_prefs.get('excluded_regions_enabled')
            else settings.EXCLUDED_REGIONS_MODE_NONE
        )
    globals()['excluded_regions_enabled'] = (
        globals()['excluded_regions_mode'] != settings.EXCLUDED_REGIONS_MODE_NONE
    )


def _ensure_parent_directory(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _read_preferences_file(path):
    with open(path, 'r', encoding='utf-8') as file:
        raw = file.read()

    if raw.strip() == "":
        return LOAD_STATUS_EMPTY, None

    try:
        return LOAD_STATUS_LOADED, json.loads(raw)
    except json.JSONDecodeError as error:
        return LOAD_STATUS_INVALID, str(error)


# Initialize module-level variables
alert_limits = _normalize_alert_limits(_default_value('alert_limits'))
enabled_postprocessors = _default_value('enabled_postprocessors')
show_all_com_ports = _default_value('show_all_com_ports')
show_plot_toolbar = _default_value('show_plot_toolbar')
recalculate_mean = _default_value('recalculate_mean')
locale = _default_value('locale')
pinned_serial_ports = _default_value('pinned_serial_ports')
distance_unit = _default_value('distance_unit')
continuous_mode = _default_value('continuous_mode')
show_spectrum = _default_value('show_spectrum')
flip_profiles = _default_value('flip_profiles')
excluded_regions_enabled = _default_value('excluded_regions_enabled')
excluded_regions = _default_value('excluded_regions')
excluded_regions_mode = _default_value('excluded_regions_mode')
distance_highlight_regions = _default_value('distance_highlight_regions')
hardness_highlight_regions = _default_value('hardness_highlight_regions')
y_lim_low_override = _default_value('y_lim_low_override')
y_lim_high_override = _default_value('y_lim_high_override')
default_y_axis_scaling = _default_value('default_y_axis_scaling')
band_pass_low = _default_value('band_pass_low')
band_pass_high = _default_value('band_pass_high')


def get_preferences_file_path():
    return preferences_file_path


def save_preferences_to_file(path=None):
    """Save all preferences to file."""
    target_path = path or preferences_file_path
    preferences = _serialized_preferences()

    try:
        _ensure_parent_directory(target_path)
        with open(target_path, 'w', encoding='utf-8') as file:
            json.dump(preferences, file, indent=2)
        print(f"Saved preferences to {target_path}")
        return True
    except Exception as error:
        print(f"Failed to write preferences to '{target_path}': {error}")
        return False


def update_preferences(updates):
    """
    Update multiple preferences at once and save to file.

    Args:
      updates: Dictionary of preference key-value pairs to update

    Raises:
      ValueError: If any key is not a valid preference
      TypeError: If value types don't match expected types
    """
    for key in updates.keys():
        if key not in _DEFAULTS:
            raise ValueError(f"Unknown preference key: '{key}'")

    for key, value in updates.items():
        if key in (
            'show_all_com_ports',
            'show_plot_toolbar',
            'recalculate_mean',
            'continuous_mode',
            'show_spectrum',
            'flip_profiles',
            'excluded_regions_enabled',
        ):
            value = bool(value)
        elif key == 'pinned_serial_ports':
            value = set(value)
        elif key == 'alert_limits':
            value = _normalize_alert_limits(value)
        elif key == 'distance_highlight_regions':
            value = normalize_distance_highlight_regions(value)
        elif key == 'hardness_highlight_regions':
            value = normalize_hardness_highlight_regions(value)

        globals()[key] = value

    save_preferences_to_file()


def get_distance_unit_info():
    """Returns DistanceUnit object for current unit."""
    return settings.DISTANCE_UNITS.get(
        distance_unit,
        settings.DISTANCE_UNITS[settings.DISTANCE_UNIT_DEFAULT],
    )


def load_preferences_from_file(path):
    target_path = os.path.abspath(path)
    previous_preferences = {
        key: copy.deepcopy(globals()[key])
        for key in _DEFAULTS.keys()
    }
    previous_path = preferences_file_path

    try:
        if not os.path.exists(target_path):
            _reset_preferences_to_defaults()
            if not save_preferences_to_file(target_path):
                raise OSError(f"Could not create '{target_path}'")
            globals()['preferences_file_path'] = target_path
            print(f"Created preferences file with defaults at {target_path}")
            return LoadPreferencesResult(LOAD_STATUS_CREATED_DEFAULTS, target_path)

        status, payload = _read_preferences_file(target_path)
        if status == LOAD_STATUS_EMPTY:
            return LoadPreferencesResult(LOAD_STATUS_EMPTY, target_path)
        if status == LOAD_STATUS_INVALID:
            return LoadPreferencesResult(LOAD_STATUS_INVALID, target_path, payload)

        _apply_loaded_preferences(payload)
        globals()['preferences_file_path'] = target_path
        print(f"Loaded preferences from {target_path}")
        return LoadPreferencesResult(LOAD_STATUS_LOADED, target_path)
    except Exception as error:
        for key, value in previous_preferences.items():
            globals()[key] = value
        globals()['preferences_file_path'] = previous_path
        return LoadPreferencesResult(LOAD_STATUS_INVALID, target_path, str(error))


def overwrite_preferences_file_with_defaults(path):
    target_path = os.path.abspath(path)
    previous_preferences = {
        key: copy.deepcopy(globals()[key])
        for key in _DEFAULTS.keys()
    }
    previous_path = preferences_file_path

    try:
        _reset_preferences_to_defaults()
        if not save_preferences_to_file(target_path):
            raise OSError(f"Could not write '{target_path}'")
        globals()['preferences_file_path'] = target_path
        print(f"Overwrote preferences file with defaults at {target_path}")
        return LoadPreferencesResult(LOAD_STATUS_CREATED_DEFAULTS, target_path)
    except Exception as error:
        for key, value in previous_preferences.items():
            globals()[key] = value
        globals()['preferences_file_path'] = previous_path
        return LoadPreferencesResult(LOAD_STATUS_INVALID, target_path, str(error))


def _load_preferences():
    result = load_preferences_from_file(default_preferences_file_path)
    if result.status in (LOAD_STATUS_LOADED, LOAD_STATUS_CREATED_DEFAULTS):
        return

    print(f"Preferences file invalid at '{default_preferences_file_path}': {result.error or result.status}")
    print("Resetting default preferences")
    overwrite_result = overwrite_preferences_file_with_defaults(default_preferences_file_path)
    if overwrite_result.status != LOAD_STATUS_CREATED_DEFAULTS:
        print(
            "Failed to restore default preferences file "
            f"'{default_preferences_file_path}': {overwrite_result.error}"
        )


_load_preferences()
