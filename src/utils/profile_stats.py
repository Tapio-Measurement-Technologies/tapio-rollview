import numpy as np
from utils.filter import bandpass_filter
import numpy as np
import settings
from utils.translation import _

# Implement here any custom more complicated profile statistics

stat_labels = {
    "mean_g": _("ALERT_LIMIT_MEAN"),
    "stdev_g": _("ALERT_LIMIT_STDEV"),
    "min_g": _("ALERT_LIMIT_MIN"),
    "max_g": _("ALERT_LIMIT_MAX"),
    "cv_pct": _("ALERT_LIMIT_CV"),
    "pp_g": _("ALERT_LIMIT_PP")
}

class Stats:
    def __init__(self):
        self.mean = np.mean
        self.std = np.std
        self.min = np.min
        self.max = np.max
        self.cv = lambda f: (np.std(f) / np.mean(f)) * 100
        self.pp = lambda f: np.max(f) - np.min(f)

        self.mean.unit = 'g'
        self.std.unit  = 'g'
        self.min.unit  = 'g'
        self.max.unit  = 'g'
        self.cv.unit   = '%'
        self.pp.unit   = 'g'

        self.mean.name = "mean_g"
        self.std.name  = "stdev_g"
        self.min.name  = "min_g"
        self.max.name  = "max_g"
        self.cv.name   = "cv_pct"
        self.pp.name   = "pp_g"


def calc_mean_profile(profiles, band_pass_low=None, band_pass_high=None, sample_interval=None):

    band_pass_low = band_pass_low if band_pass_low is not None else settings.BAND_PASS_LOW
    band_pass_high = band_pass_high if band_pass_high is not None else settings.BAND_PASS_HIGH
    sample_interval = sample_interval if sample_interval is not None else settings.SAMPLE_INTERVAL

    # Profiles shorter than NUMTAPS cannot be bandpass filtered, so
    # do not take them into account when calculating mean profile
    filtered_profiles = [
        profile for profile in profiles
        if  profile.data is not None
        and len(profile.data.hardnesses) > settings.FILTER_NUMTAPS
    ]

    if not filtered_profiles:
        return [], []

    if settings.CONTINUOUS_MODE:
        distances_list = []
        values_list = []
        current_distance = 0

        for profile in filtered_profiles:
            distances = profile.data.distances
            values = profile.data.hardnesses

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
        min_length = min(len(profile.data.distances) for profile in filtered_profiles)
        truncated_profiles = [
            np.vstack((
                profile.data.distances[:min_length],
                profile.data.hardnesses[:min_length]
            ))
            for profile in filtered_profiles
        ]
        stacked_profiles = np.stack(truncated_profiles, axis=1)
        mean_profile = np.mean(stacked_profiles, axis=1)

    distances = mean_profile[0]
    values = bandpass_filter(
        mean_profile[1], band_pass_low, band_pass_high, sample_interval)

    return distances, values
