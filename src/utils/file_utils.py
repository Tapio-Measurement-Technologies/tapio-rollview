import os
import subprocess
import platform
import struct
import numpy as np
from PySide6.QtCore import QDir

PROF_FILE_HEADER_SIZE = 128

def get_sample_step_mm(prof_file_path):
    file_size = os.path.getsize(prof_file_path)
    if file_size < 128:
        print(f"Error reading sample step for '{prof_file_path}', invalid file header")
        return 0
    with open(prof_file_path, 'rb') as file:
        # Read the header (128 bytes)
        header = file.read(128)

        # Extract the sample step from bytes 36-40
        sample_step = struct.unpack('f', header[36:40])[0]

        return sample_step

def get_measurement_distance(prof_file_path):
    file_size = os.path.getsize(prof_file_path)
    sample_step_mm = get_sample_step_mm(prof_file_path)
    distance = ((file_size - PROF_FILE_HEADER_SIZE) / 4) * (sample_step_mm / 1000)
    return distance

def read_prof_header(file_path):
    with open(file_path, 'rb') as file:
        prof_version    = file.read(4)
        serial_number   = file.read(32)
        sample_step     = file.read(4)

        try:
            prof_version    = int.from_bytes(prof_version, byteorder='little', signed=False)
            serial_number   = serial_number.decode('ISO-8859-1').split('\x00', 1)[0]
            sample_step     = struct.unpack('f', sample_step)[0]
            return {
                'prof_version':     prof_version,
                'serial_number':    serial_number,
                'sample_step':      sample_step
            }
        except Exception as e:
            print(f"Failed to parse header from file '{file_path}': {e}")
            return None

def read_prof_file(file_path):
    directory_name = os.path.basename(file_path)
    hardnesses = []

    sample_step_mm = get_sample_step_mm(file_path)
    sample_step = sample_step_mm / 1000.0

    with open(file_path, 'rb') as file:
        # Skip the header (128 bytes)
        header = file.read(128)

        # Initialize the distance calculation
        current_distance = 0.0

        while True:
            # Read the hardness value (4 bytes for a float)
            hardness_data = file.read(4)
            if len(hardness_data) < 4:
                break

            hardness = struct.unpack('f', hardness_data)[0]

            # Append the current distance and hardness to the lists
            hardnesses.append(hardness)

            # Update the distance for the next sample
            current_distance += sample_step

    # Generate distances based on the number of samples and the sample step
    if sample_step > 0:
        distances = np.arange(0, current_distance, sample_step)[:len(hardnesses)]
        data = np.array([distances, hardnesses])
    else:
        print(f"Invalid sample step in file '{file_path}'")
        data = []

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
