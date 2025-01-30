from utils.profile_stats import calc_mean_profile
from utils.translation import _
from utils.profile_stats import Stats
from models.Profile import Profile
import numpy as np
import os
import json

EXPORT_FLOAT_NUM_DECIMAL_PLACES = 3

RESAMPLE_STEP = None
BAND_PASS_HIGH = None

description = _("POSTPROCESSOR_NAME_JSON_EXPORT")


def resample_profile(distances, values, resample_step):
    """Resample data to fixed intervals using linear interpolation."""
    resampled_distances = np.arange(distances[0], distances[-1], resample_step)
    resampled_values = np.interp(resampled_distances, distances, values)
    return resampled_distances, resampled_values


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
                profile = Profile.fromfile(file_path)
                header = profile.header
                data = profile.data
                if data is not None:
                    profiles.append(profile)

                json_data = {
                    'roll_id':            folder_name,
                    'type':               'measurement',
                    'device_sn':          header.serial_number,
                    'prof_file_version':  header.prof_version,
                    'sample_step':        header.sample_step,
                    'distances':          np.round(data.distances, EXPORT_FLOAT_NUM_DECIMAL_PLACES).tolist(),
                    'values':             np.round(data.hardnesses, EXPORT_FLOAT_NUM_DECIMAL_PLACES).tolist()
                }

                json_filename = f"{os.path.splitext(file_path)[0]}.json"
                with open(json_filename, 'w') as fp:
                    json.dump(json_data, fp)
                    print(f"Exported profile '{file_name}' of roll '{
                          folder_name}' to {json_filename}.")

            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                continue

    # Create and add mean profile
    if profiles:
        mean_profile = calc_mean_profile(
            profiles, band_pass_low=None, band_pass_high=BAND_PASS_HIGH)

        mean_distances = mean_profile[0]
        mean_values = mean_profile[1]

        if RESAMPLE_STEP:
            mean_distances, mean_values = resample_profile(
                mean_distances, mean_values, RESAMPLE_STEP)

        json_data = {
            'roll_id':    folder_name,
            'type':       'mean_profile',
            'distances':  np.round(mean_distances, EXPORT_FLOAT_NUM_DECIMAL_PLACES).tolist(),
            'values':     np.round(mean_values, EXPORT_FLOAT_NUM_DECIMAL_PLACES).tolist(),
            'stats': {
                'mean_g':   round(stats.mean(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                'min_g':    round(stats.min(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                'max_g':    round(stats.max(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                'stdev_g':  round(stats.std(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                'cv_pct':   round(stats.cv(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                'pp_g':     round(stats.pp(mean_values), EXPORT_FLOAT_NUM_DECIMAL_PLACES)
            }
        }

        json_filename = os.path.join(folder_path, 'mean_profile.json')
        with open(json_filename, 'w') as fp:
            json.dump(json_data, fp)
            print(f"Exported mean profile of roll '{
                  folder_name}' to {json_filename}.")

        return True
    else:
        print("No valid .prof files were found; no mean profile JSON file was created.")
        return False
