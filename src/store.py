from PySide6.QtCore import QDir
from settings import DEFAULT_ROLL_DIRECTORY

sync_folder_path = QDir(QDir.homePath()).filePath(DEFAULT_ROLL_DIRECTORY)
recalculate_mean = False
connections = []
profiles = []
selected_profile = None
selected_directory = None

def get_profile_by_filename(filename):
    for profile in profiles:
        if profile.path == filename or profile.name == filename:
            return profile
    return None
