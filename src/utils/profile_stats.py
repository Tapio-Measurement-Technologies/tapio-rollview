import numpy as np
import settings
from utils import preferences
from utils.filter import bandpass_filter
from utils.translation import _
from utils.excluded_regions import get_included_samples

# Implement here any custom more complicated profile statistics

STAT_SPECS = [
    {
        "analysis_key": "mean",
        "name": "mean_g",
        "label": _("ALERT_LIMIT_MEAN"),
        "long_label": _("MEAN_LONG"),
        "unit": "g",
    },
    {
        "analysis_key": "std",
        "name": "stdev_g",
        "label": _("ALERT_LIMIT_STDEV"),
        "long_label": _("STDEV_LONG"),
        "unit": "g",
    },
    {
        "analysis_key": "cv",
        "name": "cv_pct",
        "label": _("ALERT_LIMIT_CV"),
        "long_label": _("CV_LONG"),
        "unit": "%",
    },
    {
        "analysis_key": "min",
        "name": "min_g",
        "label": _("ALERT_LIMIT_MIN"),
        "long_label": _("MIN_LONG"),
        "unit": "g",
    },
    {
        "analysis_key": "max",
        "name": "max_g",
        "label": _("ALERT_LIMIT_MAX"),
        "long_label": _("MAX_LONG"),
        "unit": "g",
    },
    {
        "analysis_key": "pp",
        "name": "pp_g",
        "label": _("ALERT_LIMIT_PP"),
        "long_label": _("PP_LONG"),
        "unit": "g",
    },
    {
        "analysis_key": "slope",
        "name": "slope_deg",
        "label": "Slope",
        "long_label": "Slope",
        "unit": "g/RL",
    },
]


def excluded_regions_aware(func):
    """Decorator that applies excluded regions filtering when enabled."""
    def wrapper(profile_data):
        distances = None
        data = profile_data
        if isinstance(profile_data, tuple) and len(profile_data) == 2:
            distances, data = profile_data

        if preferences.excluded_regions_mode != settings.EXCLUDED_REGIONS_MODE_NONE and len(data) > 0:
            included_data, _ = get_included_samples(
                data,
                preferences.excluded_regions,
                mode=preferences.excluded_regions_mode,
                distances=distances,
            )
            # If all data is excluded, return NaN
            if len(included_data) == 0:
                return np.nan
            return func(included_data)
        return func(data)
    return wrapper


stat_labels = {spec["name"]: spec["label"] for spec in STAT_SPECS}
analysis_display_labels = {
    spec["analysis_key"]: f"{spec['long_label']} [{spec['unit']}]"
    for spec in STAT_SPECS
}
analysis_stat_label_map = {
    display_label: analysis_key
    for analysis_key, display_label in analysis_display_labels.items()
}
analysis_to_alert_name = {
    spec["analysis_key"]: spec["name"]
    for spec in STAT_SPECS
}
stat_units = {spec["name"]: spec["unit"] for spec in STAT_SPECS}


def _get_included_data_with_positions(profile_data):
    distances = None
    data = profile_data
    if isinstance(profile_data, tuple) and len(profile_data) == 2:
        distances, data = profile_data

    data = np.asarray(data, dtype=float)
    if len(data) <= 1:
        positions = np.zeros(len(data), dtype=float)
    else:
        if distances is not None and len(distances) == len(data):
            distances = np.asarray(distances, dtype=float)
            if distances[-1] > distances[0]:
                positions = (distances - distances[0]) / (distances[-1] - distances[0])
            else:
                positions = np.zeros(len(data), dtype=float)
        else:
            positions = np.linspace(0.0, 1.0, len(data), dtype=float)

    if preferences.excluded_regions_mode != settings.EXCLUDED_REGIONS_MODE_NONE and len(data) > 0:
        included_data, excluded_ranges = get_included_samples(
            data,
            preferences.excluded_regions,
            mode=preferences.excluded_regions_mode,
            distances=distances,
        )
        if len(included_data) == 0:
            return np.array([], dtype=float), np.array([], dtype=float)

        if excluded_ranges:
            mask = np.ones(len(data), dtype=bool)
            for start_idx, end_idx in excluded_ranges:
                mask[start_idx:end_idx] = False
            positions = positions[mask]
        data = included_data

    return positions, data


def calc_slope(f):
    positions, data = _get_included_data_with_positions(f)

    if len(data) == 0:
        return np.nan
    if len(data) < 2:
        return 0.0

    slope, _ = np.polyfit(positions, data, 1)
    return float(slope)


class Stats:
    def __init__(self):
        self.mean = excluded_regions_aware(np.mean)
        self.std = excluded_regions_aware(np.std)
        self.min = excluded_regions_aware(np.min)
        self.max = excluded_regions_aware(np.max)
        self.cv = excluded_regions_aware(lambda f: (np.std(f) / np.mean(f)) * 100)
        self.pp = excluded_regions_aware(lambda f: np.max(f) - np.min(f))
        self.slope = calc_slope

        self.mean.unit = 'g'
        self.std.unit = 'g'
        self.min.unit = 'g'
        self.max.unit = 'g'
        self.cv.unit = '%'
        self.pp.unit = 'g'
        self.slope.unit = 'g/RL'

        self.mean.name = "mean_g"
        self.std.name = "stdev_g"
        self.min.name = "min_g"
        self.max.name = "max_g"
        self.cv.name = "cv_pct"
        self.pp.name = "pp_g"
        self.slope.name = "slope_deg"

        self.mean.analysis_key = "mean"
        self.std.analysis_key = "std"
        self.min.analysis_key = "min"
        self.max.analysis_key = "max"
        self.cv.analysis_key = "cv"
        self.pp.analysis_key = "pp"
        self.slope.analysis_key = "slope"


def calc_mean_profile(profiles, band_pass_low=None, band_pass_high=None, sample_interval=None):

    # Use preferences values if available, otherwise fall back to settings
    band_pass_low = band_pass_low if band_pass_low is not None else preferences.band_pass_low
    band_pass_high = band_pass_high if band_pass_high is not None else preferences.band_pass_high
    sample_interval = sample_interval if sample_interval is not None else settings.SAMPLE_INTERVAL_M
    fs = 1/sample_interval

    band_pass_low = float(band_pass_low or 0)
    band_pass_high = max(float(band_pass_high or 0), settings.BAND_PASS_HIGH_MIN)

    # Profiles shorter than NUMTAPS cannot be bandpass filtered, so
    # do not take them into account when calculating mean profile
    filtered_profiles = [
        profile for profile in profiles
        if (profile is not None and
            hasattr(profile, 'data') and
            profile.data is not None)
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
                # if len(values) > settings.FILTER_NUMTAPS:
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
