from PySide6.QtCore import QDir
import settings
import json

preferences_file_path = QDir(QDir.homePath()).filePath(settings.PREFERENCES_FILE_PATH)

alert_limits           = settings.ALERT_LIMITS_DEFAULT
enabled_postprocessors = settings.DEFAULT_ENABLED_POSTPROCESSORS
show_all_com_ports     = settings.SHOW_ALL_COM_PORTS_DEFAULT
show_plot_toolbar      = settings.SHOW_PLOT_TOOLBAR_DEFAULT
recalculate_mean       = settings.RECALCULATE_MEAN_DEFAULT
locale                 = settings.LOCALE_DEFAULT
pinned_serial_ports    = settings.PINNED_SERIAL_PORTS_DEFAULT
distance_unit          = settings.DISTANCE_UNIT_DEFAULT

def save_preferences_to_file():
  preferences = {
    "alert_limits":           alert_limits,
    "enabled_postprocessors": enabled_postprocessors,
    "show_all_com_ports":     show_all_com_ports,
    "show_plot_toolbar":      show_plot_toolbar,
    "recalculate_mean":       recalculate_mean,
    "locale":                 locale,
    "pinned_serial_ports":    list(pinned_serial_ports),
    "distance_unit":          distance_unit
  }
  try:
    with open(preferences_file_path, 'w') as file:
      json.dump(preferences, file)
      print(f"Saved preferences to {preferences_file_path}")
  except Exception as e:
    print(f"Failed to write preferences to '{preferences_file_path}': {e}")

def update_alert_limits(new_limits):
  global alert_limits
  alert_limits = new_limits
  save_preferences_to_file()

def update_enabled_postprocessors(new_enabled_postprocessors):
  global enabled_postprocessors
  enabled_postprocessors = new_enabled_postprocessors
  save_preferences_to_file()

def update_show_all_com_ports(new_show_all_com_ports):
  global show_all_com_ports
  show_all_com_ports = bool(new_show_all_com_ports)
  save_preferences_to_file()

def update_show_plot_toolbar(new_show_plot_toolbar):
  global show_plot_toolbar
  show_plot_toolbar = bool(new_show_plot_toolbar)
  save_preferences_to_file()

def update_recalculate_mean(new_recalculate_mean):
  global recalculate_mean
  recalculate_mean = bool(new_recalculate_mean)
  save_preferences_to_file()

def update_locale(new_locale):
  global locale
  locale = new_locale
  save_preferences_to_file()

def update_pinned_serial_ports(new_pinned_serial_ports):
  global pinned_serial_ports
  pinned_serial_ports = set(new_pinned_serial_ports)
  save_preferences_to_file()

def update_distance_unit(new_distance_unit):
  global distance_unit
  distance_unit = new_distance_unit
  save_preferences_to_file()

def get_distance_unit_info():
  """Returns the DistanceUnit object for the currently selected unit"""
  return settings.DISTANCE_UNITS.get(distance_unit, settings.DISTANCE_UNITS[settings.DISTANCE_UNIT_DEFAULT])

## Initialize preferences
try:
  with open(preferences_file_path, 'r') as file:
    preferences = json.load(file)

    if 'alert_limits' in preferences:
      alert_limits = preferences['alert_limits']
    if 'enabled_postprocessors' in preferences:
      enabled_postprocessors = preferences['enabled_postprocessors']
    if 'show_all_com_ports' in preferences:
      show_all_com_ports = preferences['show_all_com_ports']
    if 'show_plot_toolbar' in preferences:
      show_plot_toolbar = preferences['show_plot_toolbar']
    if 'recalculate_mean' in preferences:
      recalculate_mean = preferences['recalculate_mean']
    if 'locale' in preferences:
      locale = preferences['locale']
    if 'pinned_serial_ports' in preferences:
      pinned_serial_ports = set(preferences['pinned_serial_ports'])
    if 'distance_unit' in preferences:
      distance_unit = preferences['distance_unit']

except FileNotFoundError:
  save_preferences_to_file()
except Exception as e:
  print(f"Error reading preferences file from '{preferences_file_path}': {e}")
  print("Resetting default preferences")
  save_preferences_to_file()