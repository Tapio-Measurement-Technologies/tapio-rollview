import os
import subprocess
import platform
from PySide6.QtCore import QDir

def open_in_file_explorer(folder_path, selected_path=None):
    os_name = platform.system()
    if os_name == "Windows":
        if selected_path and os.path.exists(selected_path):
            # Use explorer.exe with /select to open and select the file
            # Convert forward slashes to backslashes for Windows
            selected_path = selected_path.replace('/', '\\')
            subprocess.run(["explorer", "/select,", selected_path])
        else:
            os.startfile(folder_path)
    elif os_name == "Darwin":
        if selected_path and os.path.exists(selected_path):
            subprocess.run(["open", "-R", selected_path])
        else:
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
    prof_files = []
    for file_info in dir_iterator:
        if file_info.fileName() != "mean.prof":
            file_path = file_info.absoluteFilePath()
            # Check if file is accessible before adding to list
            try:
                # Quick access check - try to stat the file
                os.stat(file_path)
                prof_files.append(file_path)
            except (PermissionError, OSError):
                # Skip files that can't be accessed (e.g., currently being copied)
                print(f"Skipping inaccessible file: {file_path}")
                continue
    return prof_files
