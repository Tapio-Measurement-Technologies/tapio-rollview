import os
import subprocess
import platform
from PySide6.QtCore import QDir

def open_in_file_explorer(folder_path):
    os_name = platform.system()
    if os_name == "Windows":
        os.startfile(folder_path)
    elif os_name == "Darwin":
        subprocess.run(["open", folder_path])
    elif os_name == "Linux":
        subprocess.run(["xdg-open", folder_path])
    else:
        print("Failed to open folder in file explorer, unsupported platform!")



def list_prof_files(path):
    # Validate that the path exists and is a directory
    if not path or not os.path.exists(path) or not os.path.isdir(path):
        print(f"Invalid directory path provided to list_prof_files: '{path}'")
        return []

    dir_iterator = QDir(path).entryInfoList(["*.prof"], QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
    prof_files = [file_info.absoluteFilePath() for file_info in dir_iterator if file_info.fileName() != "mean.prof"]
    return prof_files
