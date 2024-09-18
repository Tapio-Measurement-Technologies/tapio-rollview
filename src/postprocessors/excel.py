from utils.file_utils import read_prof_header, read_prof_file
import pandas as pd
import os

description = "Generate Excel file"
enabled = True

def export(folder_path):
    # Extract folder name to use as Excel file name
    folder_name = os.path.basename(folder_path.rstrip('/\\'))

    # Create an Excel writer object
    excel_file_path = os.path.join(folder_path, f"{folder_name}.xlsx")
    with pd.ExcelWriter(excel_file_path, engine='openpyxl') as writer:
        # Track if at least one sheet is added
        sheet_added = False

        # Loop through all files in the specified folder
        for file_name in os.listdir(folder_path):
            if file_name.endswith('.prof') and file_name != 'mean.prof':
                # Create the full file path
                file_path = os.path.join(folder_path, file_name)

                # Read the .prof file (adjust this part based on the structure of your .prof files)
                # Assuming .prof files are CSV-like
                try:
                    header = read_prof_header(file_path)
                    data = read_prof_file(file_path)['data']
                    columns = {
                        'Distance': data[0],
                        'Hardness': data[1]
                    }
                    df = pd.DataFrame(columns)
                    df.loc[0, 'Sample step']        = header['sample_step']
                    df.loc[0, 'Serial number']      = header['serial_number']
                    df.loc[0, '.prof file version'] = header['prof_version']
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue

                # Write the DataFrame to a sheet in the Excel file
                df.to_excel(writer, sheet_name=file_name, index=False)
                sheet_added = True

        # Check if at least one sheet was added
        if not sheet_added:
            # Add a default empty sheet if no sheets were added
            pd.DataFrame().to_excel(writer, sheet_name='Sheet1', index=False)
            print("No valid .prof files were found; added a default empty sheet.")

    print(f"Excel file '{excel_file_path}' has been created successfully.")