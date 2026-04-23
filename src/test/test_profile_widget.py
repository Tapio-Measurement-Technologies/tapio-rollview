import unittest
import copy
from unittest.mock import patch

import numpy as np
import settings
from PySide6.QtWidgets import QApplication

from models.Profile import Profile, ProfileData, ProfileHeader
from gui.widgets.ProfileWidget import ProfileWidget
from utils.highlighted_regions import (
    AbsoluteMeanOffsetHardnessHighlightRegion,
    DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE,
    DistanceHighlightRegion,
)
from utils import preferences


class TestProfileWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        self.original_distance_highlight_regions = preferences.distance_highlight_regions
        self.original_hardness_highlight_regions = preferences.hardness_highlight_regions
        self.original_distance_unit = preferences.distance_unit
        self.original_alert_limits = copy.deepcopy(preferences.alert_limits)

    def tearDown(self):
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions
        preferences.distance_highlight_regions = self.original_distance_highlight_regions
        preferences.hardness_highlight_regions = self.original_hardness_highlight_regions
        preferences.distance_unit = self.original_distance_unit
        preferences.alert_limits = self.original_alert_limits

    def test_sync_toolbar_layout_positions_updates_saved_home_geometry(self):
        widget = ProfileWidget()
        try:
            widget.profile_ax.plot([0, 1], [0, 1])
            widget.figure.tight_layout()
            widget._reset_toolbar_history()

            nav_state = widget.toolbar._nav_stack._elements[0]
            _, (_, (_, original_active_pos)) = next(iter(nav_state.items()))

            widget.figure.subplots_adjust(left=0.25, right=0.95, bottom=0.22, top=0.88)
            widget._sync_toolbar_layout_positions()

            _, (_, (_, synced_active_pos)) = next(iter(nav_state.items()))
            current_active_pos = widget.profile_ax.get_position().frozen()

            self.assertNotEqual(original_active_pos.bounds, synced_active_pos.bounds)
            self.assertEqual(synced_active_pos.bounds, current_active_pos.bounds)
        finally:
            widget.close()

    def test_absolute_excluded_region_plot_ranges_follow_selected_distance_unit(self):
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_ABSOLUTE
        preferences.excluded_regions = "1-2"
        preferences.distance_unit = "in"

        widget = ProfileWidget()
        try:
            conversion_factor = preferences.get_distance_unit_info().conversion_factor
            plot_ranges = widget._get_excluded_region_plot_ranges([0.0, 1.0, 2.0, 3.0], conversion_factor)

            self.assertEqual(len(plot_ranges), 1)
            self.assertAlmostEqual(plot_ranges[0][0], 1.0)
            self.assertAlmostEqual(plot_ranges[0][1], 2.0)
        finally:
            widget.close()

    def test_spectrum_plot_data_uses_frequency_limits_in_1m(self):
        widget = ProfileWidget()
        try:
            profile = [0.0] * 8000
            frequencies, amplitudes = widget._get_spectrum_plot_data(profile)

            self.assertGreater(len(frequencies), 0)
            self.assertEqual(len(frequencies), len(amplitudes))
            self.assertGreaterEqual(frequencies[0], settings.SPECTRUM_LOWER_LIMIT_1M)
            self.assertLessEqual(frequencies[-1], settings.SPECTRUM_UPPER_LIMIT_1M)
            self.assertAlmostEqual(frequencies[-1], settings.SPECTRUM_UPPER_LIMIT_1M)
        finally:
            widget.close()

    def test_absolute_distance_highlight_region_plot_ranges_follow_selected_distance_unit(self):
        preferences.distance_highlight_regions = [
            DistanceHighlightRegion(start=1.0, end=2.0, mode=DISTANCE_HIGHLIGHT_MODE_ABSOLUTE, color="tab:orange")
        ]
        preferences.distance_unit = "in"

        widget = ProfileWidget()
        try:
            conversion_factor = preferences.get_distance_unit_info().conversion_factor
            plot_ranges = widget._get_distance_highlight_region_plot_ranges([0.0, 1.0, 2.0, 3.0], conversion_factor)

            self.assertEqual(plot_ranges, [(1.0, 2.0, "tab:orange")])
        finally:
            widget.close()

    def test_hardness_highlight_region_plot_ranges_use_mean_profile_mean(self):
        preferences.hardness_highlight_regions = [
            AbsoluteMeanOffsetHardnessHighlightRegion(
                color="tab:orange",
                lower_offset=-1.0,
                upper_offset=2.0,
            )
        ]

        widget = ProfileWidget()
        try:
            plot_ranges = widget._get_hardness_highlight_region_plot_ranges(
                [0.0, 1.0, 2.0],
                [9.0, 10.0, 11.0],
            )

            self.assertEqual(plot_ranges, [(9.0, 12.0, "tab:orange", True, 10.0)])
        finally:
            widget.close()

    def test_distance_highlight_visualization_draws_edge_vlines(self):
        preferences.distance_highlight_regions = [
            DistanceHighlightRegion(start=1.0, end=2.0, mode=DISTANCE_HIGHLIGHT_MODE_ABSOLUTE, color="tab:orange")
        ]

        widget = ProfileWidget()
        try:
            with patch.object(widget.profile_ax, "axvline") as axvline_mock:
                widget._draw_distance_highlight_regions_visualization([0.0, 1.0, 2.0, 3.0], 1.0)

            self.assertEqual(axvline_mock.call_count, 2)
        finally:
            widget.close()

    def test_hardness_highlight_visualization_draws_edges_and_mean_line(self):
        preferences.hardness_highlight_regions = [
            AbsoluteMeanOffsetHardnessHighlightRegion(
                color="tab:orange",
                lower_offset=-1.0,
                upper_offset=2.0,
            )
        ]

        widget = ProfileWidget()
        try:
            with patch.object(widget.profile_ax, "axhline") as axhline_mock:
                widget._draw_hardness_highlight_regions_visualization([0.0, 1.0, 2.0], [9.0, 10.0, 11.0])

            self.assertEqual(axhline_mock.call_count, 3)
        finally:
            widget.close()

    def test_hardness_highlight_visualization_does_not_expand_short_profile_x_range(self):
        profile = Profile(
            path="short.prof",
            data=ProfileData(
                distances=np.array([0.0, 0.2, 0.4]),
                hardnesses=np.array([9.0, 10.0, 11.0]),
            ),
            header=ProfileHeader(prof_version=1, serial_number="test", sample_step=1.0),
            file_size=0,
            date_modified=0.0,
        )

        widget = ProfileWidget()
        try:
            preferences.hardness_highlight_regions = []
            widget.update_plot([profile], "dir")
            x_limits_without_highlight = widget.profile_ax.get_xlim()

            preferences.hardness_highlight_regions = [
                AbsoluteMeanOffsetHardnessHighlightRegion(
                    color="tab:orange",
                    lower_offset=-1.0,
                    upper_offset=1.0,
                )
            ]
            widget.update_plot([profile], "dir")
            x_limits_with_highlight = widget.profile_ax.get_xlim()

            self.assertEqual(x_limits_with_highlight, x_limits_without_highlight)
        finally:
            widget.close()

    def test_distance_highlight_visualization_does_not_expand_short_profile_x_range(self):
        profile = Profile(
            path="short.prof",
            data=ProfileData(
                distances=np.array([0.0, 0.2, 0.4]),
                hardnesses=np.array([9.0, 10.0, 11.0]),
            ),
            header=ProfileHeader(prof_version=1, serial_number="test", sample_step=1.0),
            file_size=0,
            date_modified=0.0,
        )

        widget = ProfileWidget()
        try:
            preferences.distance_highlight_regions = []
            widget.update_plot([profile], "dir")
            x_limits_without_highlight = widget.profile_ax.get_xlim()

            preferences.distance_highlight_regions = [
                DistanceHighlightRegion(
                    start=0.1,
                    end=0.3,
                    mode=DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
                    color="tab:orange",
                )
            ]
            widget.update_plot([profile], "dir")
            x_limits_with_highlight = widget.profile_ax.get_xlim()

            self.assertEqual(x_limits_with_highlight, x_limits_without_highlight)
        finally:
            widget.close()

    def test_stats_widget_refreshes_alert_limits_after_preferences_change(self):
        widget = ProfileWidget()
        try:
            original_mean_limit = next(
                limit for limit in preferences.alert_limits if limit["name"] == "mean_g"
            )
            original_mean_limit["max"] = 10.0

            widget.stats_widget.update_data(([0.0, 1.0], [1.0, 2.0]))
            self.assertEqual(widget.stats_widget.widgets[0].limit["max"], 10.0)

            preferences.alert_limits = [
                copy.deepcopy(limit) if limit["name"] != "mean_g"
                else copy.deepcopy(limit) | {"max": 2.5}
                for limit in preferences.alert_limits
            ]

            widget.stats_widget.update_data(([0.0, 1.0], [1.0, 2.0]))
            self.assertEqual(widget.stats_widget.widgets[0].limit["max"], 2.5)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
