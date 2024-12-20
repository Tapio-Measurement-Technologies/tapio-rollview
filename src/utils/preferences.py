from PySide6.QtCore import QDir
import settings
import json

preferences_file_path = QDir(QDir.homePath()).filePath(settings.PREFERENCES_FILE_PATH)

alert_limits = settings.ALERT_LIMITS_DEFAULT
enabled_postprocessors = settings.DEFAULT_ENABLED_POSTPROCESSORS

def save_preferences_to_file():
  preferences = {
    "alert_limits": alert_limits,
    "enabled_postprocessors": enabled_postprocessors
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


## Initialize preferences
try:
  with open(preferences_file_path, 'r') as file:
    preferences = json.load(file)

    if 'alert_limits' in preferences:
      alert_limits = preferences['alert_limits']
    if 'enabled_postprocessors' in preferences:
      enabled_postprocessors = preferences['enabled_postprocessors']

except FileNotFoundError:
  save_preferences_to_file()
except Exception as e:
  print(f"Error reading preferences file from '{preferences_file_path}': {e}")
  print("Resetting default preferences")
  save_preferences_to_file()