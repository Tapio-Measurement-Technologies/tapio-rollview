import unittest
import warnings

import numpy as np

from models.Profile import Profile, ProfileData, ProfileHeader
from utils.profile_stats import Stats, calc_mean_profile


class TestProfileStats(unittest.TestCase):
    def test_empty_profile_data_is_ignored_without_runtime_warning(self):
        profile = Profile(
            path="header-only.prof",
            data=ProfileData(
                distances=np.array([]),
                hardnesses=np.array([]),
            ),
            header=ProfileHeader(prof_version=1, serial_number="test", sample_step=1.0),
            file_size=128,
            date_modified=0.0,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            distances, values = calc_mean_profile([profile])

        self.assertEqual(distances, [])
        self.assertEqual(values, [])

    def test_empty_stat_data_returns_nan_without_runtime_warning(self):
        stats = Stats()

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            value = stats.mean(([], []))

        self.assertTrue(np.isnan(value))


if __name__ == "__main__":
    unittest.main()
