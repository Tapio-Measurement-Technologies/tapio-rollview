from PySide6.QtCore import QDir
import copy
import settings
import json

preferences_file_path = QDir(QDir.homePath()).filePath(settings.PREFERENCES_FILE_PATH)

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
    'y_lim_low_override': settings.Y_LIM_LOW_OVERRIDE_DEFAULT,
    'y_lim_high_override': settings.Y_LIM_HIGH_OVERRIDE_DEFAULT,
    'default_y_axis_scaling': settings.Y_AXIS_SCALING_DEFAULT,
    'band_pass_low': settings.BAND_PASS_LOW_DEFAULT,
    'band_pass_high': settings.BAND_PASS_HIGH_DEFAULT,
}

# Type converters for loading from JSON (for special types like sets)
_LOADERS = {
    'pinned_serial_ports': set,
}

# Type converters for saving to JSON (for special types like sets)
_SAVERS = {
    'pinned_serial_ports': list,
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
y_lim_low_override = _default_value('y_lim_low_override')
y_lim_high_override = _default_value('y_lim_high_override')
default_y_axis_scaling = _default_value('default_y_axis_scaling')
band_pass_low = _default_value('band_pass_low')
band_pass_high = _default_value('band_pass_high')

def save_preferences_to_file():
  """Save all preferences to file"""
  preferences = {}
  for key in _DEFAULTS.keys():
    value = globals()[key]
    # Apply saver conversion if needed (e.g., set to list)
    if key in _SAVERS:
      value = _SAVERS[key](value)
    preferences[key] = value

  try:
    with open(settings.PREFERENCES_FILE_PATH, 'w') as file:
      json.dump(preferences, file, indent=2)
      print(f"Saved preferences to {settings.PREFERENCES_FILE_PATH}")
  except Exception as e:
    print(f"Failed to write preferences to '{settings.PREFERENCES_FILE_PATH}': {e}")

def update_preferences(updates):
  """
  Update multiple preferences at once and save to file.

  Args:
    updates: Dictionary of preference key-value pairs to update

  Raises:
    ValueError: If any key is not a valid preference
    TypeError: If value types don't match expected types
  """
  # Validate all keys first before making any changes
  for key in updates.keys():
    if key not in _DEFAULTS:
      raise ValueError(f"Unknown preference key: '{key}'")

  # Update all preferences in memory
  for key, value in updates.items():
    # Apply type conversions based on key
    if key in ('show_all_com_ports', 'show_plot_toolbar', 'recalculate_mean',
               'continuous_mode', 'show_spectrum', 'flip_profiles', 'excluded_regions_enabled'):
      value = bool(value)
    elif key == 'pinned_serial_ports':
      value = set(value)
    elif key == 'alert_limits':
      value = _normalize_alert_limits(value)

    globals()[key] = value

  # Save once after all updates
  save_preferences_to_file()

def get_distance_unit_info():
  """Returns the DistanceUnit object for the currently selected unit"""
  return settings.DISTANCE_UNITS.get(distance_unit, settings.DISTANCE_UNITS[settings.DISTANCE_UNIT_DEFAULT])

## Initialize preferences from file
def _load_preferences():
  """Load preferences from file and update module-level variables"""
  try:
    with open(settings.PREFERENCES_FILE_PATH, 'r') as file:
      loaded_prefs = json.load(file)

      for key in _DEFAULTS.keys():
        if key in loaded_prefs:
          value = loaded_prefs[key]
          # Apply loader conversion if needed (e.g., list to set)
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

      print(f"Loaded preferences from {settings.PREFERENCES_FILE_PATH}")

  except FileNotFoundError:
    print(f"Preferences file not found, creating with defaults")
    save_preferences_to_file()
  except Exception as e:
    print(f"Error reading preferences file from '{settings.PREFERENCES_FILE_PATH}': {e}")
    print("Resetting default preferences")
    save_preferences_to_file()

# Load preferences on module import
_load_preferences()
