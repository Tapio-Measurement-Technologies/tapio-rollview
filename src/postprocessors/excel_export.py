from utils.file_utils import read_prof_header, read_prof_file
from utils.profile_stats import calc_mean_profile
import pandas as pd
import os

description = "Export to Excel file"
enabled = True

def run(folder_path) -> bool:
    """
    Exports data from '.prof' files in a specified folder to an Excel file.

    This function reads '.prof' files (excluding 'mean.prof') from a given folder, extracts data from each file,
    and writes it into separate sheets of an Excel file. The Excel file is saved in the same folder with the
    folder name as its file name.

    Args:
        folder_path (str): The path to the folder containing the '.prof' files.

    Returns:
        bool: True if the Excel file is successfully created, False if no valid '.prof' files are found or an error occurs.

    The function performs the following steps:
    1. Extracts the folder name from the provided folder path to use as the Excel file name.
    2. Loops through all files in the specified folder and processes those with a '.prof' extension (excluding 'mean.prof').
    3. Reads the header and data from each '.prof' file using helper functions `read_prof_header` and `read_prof_file`.
    4. Creates a pandas DataFrame for each file's data, including metadata such as sample step, serial number, and file version.
    5. Collects all DataFrames and writes them into separate sheets in an Excel file using `xlsxwriter`.
    6. Returns True if the Excel file is successfully created and contains at least one sheet; otherwise, returns False.

    Notes:
    - The function uses `pandas` for data manipulation and `xlsxwriter` for writing Excel files.
    - The function prints messages indicating success, errors in reading files, or lack of valid files.
    - Ensure that the helper functions `read_prof_header` and `read_prof_file` are defined and implemented correctly.

    Example:
        run('/path/to/folder')
    """

    # Extract folder name to use as Excel file name
    folder_name = os.path.basename(folder_path.rstrip('/\\'))

    # Create an Excel writer object
    excel_file_path = os.path.join(folder_path, f"{folder_name}.xlsx")

    profiles = []
    sheets = []

    # Loop through all files in the specified folder
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.prof') and file_name != 'mean.prof':
            # Create the full file path
            file_path = os.path.join(folder_path, file_name)

            try:
                header = read_prof_header(file_path)
                data = read_prof_file(file_path)
                if data['data'] is not None:
                    profiles.append(data)
                columns = {
                    'Distance': data['data'][0],
                    'Hardness': data['data'][1]
                }
                df = pd.DataFrame(columns)
                df.loc[0, 'Sample step']        = header['sample_step']
                df.loc[0, 'Serial number']      = header['serial_number']
                df.loc[0, '.prof file version'] = header['prof_version']

                sheets.append((df, file_name))
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue

    # Create and add mean profile
    if profiles:
        mean_profile = calc_mean_profile(profiles)
        columns = {
            'Distance':      mean_profile[0],
            'Mean hardness': mean_profile[1]
        }
        df = pd.DataFrame(columns)
        sheets.insert(0, (df, "Mean profile"))

    # Only create the Excel file if there are sheets to add
    if sheets:
        # Create an Excel writer object
        with pd.ExcelWriter(excel_file_path, engine='xlsxwriter') as writer:
            # Write each DataFrame to a separate sheet
            for df, file_name in sheets:
                df.to_excel(writer, sheet_name=file_name, index=False)

        print(f"Excel file '{excel_file_path}' has been created successfully.")
        return True
    else:
        print("No valid .prof files were found; no Excel file was created.")
        return False