import numpy as np
from utils.filter import bandpass_filter
import numpy as np
import settings
from utils import preferences
from utils.translation import _
from utils.excluded_regions import get_included_samples

# Implement here any custom more complicated profile statistics


def excluded_regions_aware(func):
    """Decorator that applies excluded regions filtering when enabled."""
    def wrapper(f):
        if preferences.excluded_regions_enabled and len(f) > 0:
            included_data, _ = get_included_samples(f, preferences.excluded_regions)
            # If all data is excluded, return NaN
            if len(included_data) == 0:
                return np.nan
            return func(included_data)
        return func(f)
    return wrapper

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
        self.mean = excluded_regions_aware(np.mean)
        self.std = excluded_regions_aware(np.std)
        self.min = excluded_regions_aware(np.min)
        self.max = excluded_regions_aware(np.max)
        self.cv = excluded_regions_aware(lambda f: (np.std(f) / np.mean(f)) * 100)
        self.pp = excluded_regions_aware(lambda f: np.max(f) - np.min(f))

        self.mean.unit = 'g'
        self.std.unit = 'g'
        self.min.unit = 'g'
        self.max.unit = 'g'
        self.cv.unit = '%'
        self.pp.unit = 'g'

        self.mean.name = "mean_g"
        self.std.name = "stdev_g"
        self.min.name = "min_g"
        self.max.name = "max_g"
        self.cv.name = "cv_pct"
        self.pp.name = "pp_g"


def calc_mean_profile(profiles, band_pass_low=None, band_pass_high=None, sample_interval=None):

    # Use preferences values if available, otherwise fall back to settings
    band_pass_low = band_pass_low if band_pass_low is not None else preferences.band_pass_low
    band_pass_high = band_pass_high if band_pass_high is not None else preferences.band_pass_high
    sample_interval = sample_interval if sample_interval is not None else settings.SAMPLE_INTERVAL_M
    fs = 1/sample_interval

    # Profiles shorter than NUMTAPS cannot be bandpass filtered, so
    # do not take them into account when calculating mean profile
    filtered_profiles = [
        profile for profile in profiles
        if (profile is not None and
            hasattr(profile, 'data') and
            profile.data is not None and
            len(profile.data.hardnesses) > settings.FILTER_NUMTAPS)
    ]

    if not filtered_profiles:
        return [], []

    if preferences.continuous_mode:
        distances_list = []
        values_list = []
        current_distance = 0

        # Track distance offsets from all profiles, including those too short
        for profile in profiles:
            if (profile is not None and
                hasattr(profile, 'data') and
                profile.data is not None):

                distances = profile.data.distances
                values = profile.data.hardnesses

                # Check if this profile is long enough to include in mean
                if len(values) > settings.FILTER_NUMTAPS:
                    # Adjust distances to be continuous
                    distances_adjusted = distances + current_distance
                    distances_list.append(distances_adjusted)
                    values_list.append(values)

                # Update current_distance for all profiles (including short ones)
                current_distance += distances[-1] + settings.SAMPLE_INTERVAL_M

        # Stack the distances and values
        all_distances = np.concatenate(distances_list)
        all_values = np.concatenate(values_list)

        mean_profile = np.array([all_distances, all_values])

    else:
        min_length = min(len(profile.data.distances)
                         for profile in filtered_profiles)
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
        mean_profile[1], band_pass_low, band_pass_high, fs)

    return distances, values
