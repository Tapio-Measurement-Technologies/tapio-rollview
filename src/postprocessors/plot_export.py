from gui.widgets.chart import Chart
from utils.file_utils import read_prof_file
import os

description = "Export plot image"
enabled = True

def run(folder_path) -> bool:
    chart = Chart()
    profiles = []
    folder_name = os.path.basename(folder_path.rstrip('/\\'))
    save_path = os.path.join(folder_path, f"{folder_name}.png")

    # Loop through all files in the specified folder
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.prof') and file_name != 'mean.prof':
            # Create the full file path
            file_path = os.path.join(folder_path, file_name)

            try:
                data = read_prof_file(file_path)
                profiles.append(data)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue

    if profiles:
        chart.update_plot(profiles, folder_name)
        chart.figure.savefig(save_path)
        print(f"Successfully generated plot image for folder '{folder_path}'!")
        return True
    else:
        print(f"Failed to generate plot image for folder '{folder_path}'!")
        return False