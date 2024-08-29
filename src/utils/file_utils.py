import os
import subprocess
import platform
import struct
import numpy as np
from PySide6.QtCore import QDir


def read_prof_file(file_path):
    directory_name = os.path.basename(file_path)
    distances = []
    hardnesses = []
    with open(file_path, 'rb') as file:
        while True:
            pair = file.read(8)
            if not pair:
                break
            distance, hardness = struct.unpack('ff', pair)

            distances.append(distance)
            hardnesses.append(hardness)
    data = np.array([distances, hardnesses])
    return {
        "name": directory_name,
        "data": data
    }

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
    dir_iterator = QDir(path).entryInfoList(["*.prof"], QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
    prof_files = [file_info.absoluteFilePath() for file_info in dir_iterator if file_info.fileName() != "mean.prof"]
    return prof_files
