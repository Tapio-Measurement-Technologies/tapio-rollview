from utils.file_utils import read_prof_header, read_prof_file
from utils.profile_stats import calc_mean_profile
from utils.profile_stats import Stats
import os
import json

description = "Export to JSON file"
enabled = False

def run(folder_path) -> bool:
    stats = Stats()
    folder_name = os.path.basename(folder_path.rstrip('/\\'))
    profiles = []

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

                json_data = {
                    'roll_id':            folder_name,
                    'type':               'measurement',
                    'device_sn':          header['serial_number'],
                    'prof_file_version':  header['prof_version'],
                    'sample_step':        header['sample_step'],
                    'distances':          data['data'][0].tolist(),
                    'values':             data['data'][1].tolist()
                }

                json_filename = f"{os.path.splitext(file_path)[0]}.json"
                with open(json_filename, 'w') as fp:
                  json.dump(json_data, fp)
                  print(f"Exported profile '{file_name}' of roll '{folder_name}' to {json_filename}.")

            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                continue

    # Create and add mean profile
    if profiles:
        mean_profile = calc_mean_profile(profiles)
        mean_values = mean_profile[1]
        json_data = {
            'roll_id':    folder_name,
            'type':       'mean_profile',
            'distances':  mean_profile[0].tolist(),
            'values':     mean_profile[1].tolist(),
            'stats': {
                'mean_g':   stats.mean(mean_values),
                'min_g':    stats.min(mean_values),
                'max_g':    stats.max(mean_values),
                'stdev_g':  stats.std(mean_values),
                'cv_pct':   stats.cv(mean_values),
                'pp_g':     stats.pp(mean_values)
            }
        }

        json_filename = os.path.join(folder_path, 'mean_profile.json')
        with open(json_filename, 'w') as fp:
          json.dump(json_data, fp)
          print(f"Exported mean profile of roll '{folder_name}' to {json_filename}.")

        return True
    else:
        print("No valid .prof files were found; no mean profile JSON file was created.")
        return False