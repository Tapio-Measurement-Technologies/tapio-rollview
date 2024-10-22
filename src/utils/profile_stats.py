import numpy as np
from utils.filter import bandpass_filter
import numpy as np
import settings

# Implement here any custom more complicated profile statistics
class Stats:
    def __init__(self):
        self.mean   = np.mean
        self.std    = np.std
        self.min    = np.min
        self.max    = np.max
        self.cv     = lambda f: (np.std(f) / np.mean(f)) * 100
        self.pp     = lambda f: np.max(f) - np.min(f)

        self.mean.unit  = 'g'
        self.std.unit   = 'g'
        self.min.unit   = 'g'
        self.max.unit   = 'g'
        self.cv.unit    = '%'
        self.pp.unit    = 'g'

        self.mean.label = 'Mean'
        self.std.label  = 'Stdev'
        self.min.label  = 'Min'
        self.max.label  = 'Max'
        self.cv.label   = 'CV'
        self.pp.label   = 'P-p'

def calc_mean_profile(profiles, continuous=False):
    if not profiles:
        return [], []

    if settings.CONTINUOUS_MODE:
        distances_list = []
        values_list = []
        current_distance = 0

        for profile in profiles:
            distances = profile['data'][0]
            values = profile['data'][1]

            # Adjust distances to be continuous
            distances_adjusted = distances + current_distance
            current_distance = distances_adjusted[-1] + 1

            distances_list.append(distances_adjusted)
            values_list.append(values)

        # Stack the distances and values
        all_distances = np.concatenate(distances_list)
        all_values = np.concatenate(values_list)

        mean_profile = np.array([all_distances, all_values])

    else:
        min_length = min(profile['data'].shape[1] for profile in profiles)
        truncated_profiles = [profile['data'][:, :min_length] for profile in profiles]
        stacked_profiles = np.stack(truncated_profiles, axis=1)
        mean_profile = np.mean(stacked_profiles, axis=1)

    distances = mean_profile[0]
    values = bandpass_filter(mean_profile[1], settings.BAND_PASS_LOW, settings.BAND_PASS_HIGH,
                             settings.SAMPLE_INTERVAL)

    return distances, values
