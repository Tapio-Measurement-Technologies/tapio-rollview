from PySide6.QtCore import QDir
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
}

# Type converters for loading from JSON (for special types like sets)
_LOADERS = {
    'pinned_serial_ports': set,
}

# Type converters for saving to JSON (for special types like sets)
_SAVERS = {
    'pinned_serial_ports': list,
}

# Initialize module-level variables
alert_limits = _DEFAULTS['alert_limits']
enabled_postprocessors = _DEFAULTS['enabled_postprocessors']
show_all_com_ports = _DEFAULTS['show_all_com_ports']
show_plot_toolbar = _DEFAULTS['show_plot_toolbar']
recalculate_mean = _DEFAULTS['recalculate_mean']
locale = _DEFAULTS['locale']
pinned_serial_ports = _DEFAULTS['pinned_serial_ports']
distance_unit = _DEFAULTS['distance_unit']
continuous_mode = _DEFAULTS['continuous_mode']
show_spectrum = _DEFAULTS['show_spectrum']

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
    with open(preferences_file_path, 'w') as file:
      json.dump(preferences, file, indent=2)
      print(f"Saved preferences to {preferences_file_path}")
  except Exception as e:
    print(f"Failed to write preferences to '{preferences_file_path}': {e}")

def update_preference(key, value):
  """Generic function to update any preference"""
  if key not in _DEFAULTS:
    raise ValueError(f"Unknown preference key: {key}")

  globals()[key] = value
  save_preferences_to_file()

# Convenience functions that call the generic update_preference
def update_alert_limits(new_limits):
  update_preference('alert_limits', new_limits)

def update_enabled_postprocessors(new_enabled_postprocessors):
  update_preference('enabled_postprocessors', new_enabled_postprocessors)

def update_show_all_com_ports(new_show_all_com_ports):
  update_preference('show_all_com_ports', bool(new_show_all_com_ports))

def update_show_plot_toolbar(new_show_plot_toolbar):
  update_preference('show_plot_toolbar', bool(new_show_plot_toolbar))

def update_recalculate_mean(new_recalculate_mean):
  update_preference('recalculate_mean', bool(new_recalculate_mean))

def update_locale(new_locale):
  update_preference('locale', new_locale)

def update_pinned_serial_ports(new_pinned_serial_ports):
  update_preference('pinned_serial_ports', set(new_pinned_serial_ports))

def update_distance_unit(new_distance_unit):
  update_preference('distance_unit', new_distance_unit)

def update_continuous_mode(new_continuous_mode):
  update_preference('continuous_mode', bool(new_continuous_mode))

def update_show_spectrum(new_show_spectrum):
  update_preference('show_spectrum', bool(new_show_spectrum))

def get_distance_unit_info():
  """Returns the DistanceUnit object for the currently selected unit"""
  return settings.DISTANCE_UNITS.get(distance_unit, settings.DISTANCE_UNITS[settings.DISTANCE_UNIT_DEFAULT])

## Initialize preferences from file
def _load_preferences():
  """Load preferences from file and update module-level variables"""
  try:
    with open(preferences_file_path, 'r') as file:
      loaded_prefs = json.load(file)

      for key in _DEFAULTS.keys():
        if key in loaded_prefs:
          value = loaded_prefs[key]
          # Apply loader conversion if needed (e.g., list to set)
          if key in _LOADERS:
            value = _LOADERS[key](value)
          globals()[key] = value

      print(f"Loaded preferences from {preferences_file_path}")

  except FileNotFoundError:
    print(f"Preferences file not found, creating with defaults")
    save_preferences_to_file()
  except Exception as e:
    print(f"Error reading preferences file from '{preferences_file_path}': {e}")
    print("Resetting default preferences")
    save_preferences_to_file()

# Load preferences on module import
_load_preferences()
