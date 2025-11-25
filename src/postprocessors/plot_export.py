from gui.widgets.ProfileWidget import ProfileWidget
from utils.translation import _
from models.Profile import Profile
import os

description = _("POSTPROCESSOR_NAME_PLOT_EXPORT")

def run(folder_path) -> bool:
    """
    Generates and exports a plot image from `.prof` files in a given folder.

    This function scans the specified folder for `.prof` files (excluding `mean.prof`),
    reads the data from each of these files, and generates a plot using the `ProfileWidget` widget.
    The generated plot is then saved as an image (`.png`) in the same folder, named after the folder.

    Args:
        folder_path (str): The path to the folder containing the `.prof` files.

    Returns:
        bool: Returns `True` if the plot image was successfully generated and saved,
            otherwise returns `False` if no valid profiles were found or an error occurred.

    Dependencies:
        - ProfileWidget: A widget class for creating and managing charts.
        - read_prof_file: A utility function for reading `.prof` files.
        - os: Standard library module used for path manipulations and file operations.

    Behavior:
        - Only `.prof` files are considered, excluding `mean.prof`.
        - If an error occurs while reading a `.prof` file, it skips that file and continues processing.
        - If no valid `.prof` files are found, the function will return `False` and no image will be saved.
    """
    profile_widget = ProfileWidget()
    profiles = []
    folder_name = os.path.basename(folder_path.rstrip('/\\'))
    save_path = os.path.join(folder_path, f"{folder_name}.png")

    # Loop through all files in the specified folder
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.prof') and file_name != 'mean.prof':
            # Create the full file path
            file_path = os.path.join(folder_path, file_name)

            try:
                profile = Profile.fromfile(file_path)
                profiles.append(profile)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue

    if profiles:
        profile_widget.update_plot(profiles, folder_name, show_stats_in_title=True)
        profile_widget.figure.savefig(save_path)
        print(f"Successfully generated plot image for folder '{folder_path}'!")
        return True
    else:
        print(f"Failed to generate plot image for folder '{folder_path}'!")
        return False