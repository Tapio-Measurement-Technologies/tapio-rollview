import os
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


def list_prof_files(path):
    dir_iterator = QDir(path).entryInfoList(["*.prof"], QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
    prof_files = [file_info.absoluteFilePath() for file_info in dir_iterator if file_info.fileName() != "mean.prof"]
    return prof_files
