import unittest
import copy
import warnings
from unittest.mock import patch

import numpy as np
import settings
from PySide6.QtWidgets import QApplication

from models.Profile import Profile, ProfileData, ProfileHeader
from gui.widgets.ProfileWidget import ProfileWidget
from test.qtcleanup import destroy
from gui.widgets.stats import MISSING
from utils.highlighted_regions import (
    AbsoluteMeanOffsetHardnessHighlightRegion,
    DISTANCE_HIGHLIGHT_MODE_ABSOLUTE,
    HARDNESS_HIGHLIGHT_MODE_MEAN_OFFSET_ABSOLUTE,
    DistanceHighlightRegion,
)
from utils import preferences


def _synthetic_profiles(count):
    """*count* profiles of the same shape, oldest first."""
    distances = np.linspace(0.0, 6.0, 120)
    return [
        Profile(
            path=f"synthetic-{index}.prof",
            data=ProfileData(
                distances=distances,
                hardnesses=40.0 + float(index) + np.sin(distances),
            ),
            header=ProfileHeader(prof_version=1, serial_number="SN0", sample_step=0.05),
            file_size=distances.size * 4,
            date_modified=float(index),
        )
        for index in range(count)
    ]


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

    def test_the_chart_is_in_the_theme_before_anything_is_plotted(self):
        """The blank panel is the chart's own colour from the first frame.

        The canvas paints itself in the figure's colour while it waits for a
        first render, and Matplotlib's default figure is white - which in a
        dark session is a panel of the wrong theme where the chart will be.
        """
        from theme import mpl as tapio_mpl

        widget = ProfileWidget()
        try:
            expected = tapio_mpl.current.color("surface").upper()
            red, green, blue = (
                int(round(channel * 255))
                for channel in widget.figure.get_facecolor()[:3]
            )
            self.assertEqual(f"#{red:02X}{green:02X}{blue:02X}", expected)
        finally:
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

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
            destroy(widget)

    def test_clear_plot_display_hides_graph_until_next_update(self):
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
            widget.clear_plot_display()

            self.assertTrue(widget.canvas.isHidden())
            self.assertTrue(widget.toolbar.isHidden())
            self.assertTrue(widget.stats_widget.isHidden())
            self.assertTrue(widget.empty_state_label.isHidden())
            self.assertEqual(widget.figure.axes, [])

            widget.update_plot([profile], "dir")

            self.assertFalse(widget.canvas.isHidden())
            self.assertFalse(widget.stats_widget.isHidden())
            self.assertTrue(widget.empty_state_label.isHidden())
            self.assertGreater(len(widget.figure.axes), 0)
        finally:
            destroy(widget)

    def test_update_plot_without_profiles_shows_message_outside_plot_and_resets_stats(self):
        profile = Profile(
            path="empty.prof",
            data=None,
            header=ProfileHeader(prof_version=1, serial_number="test", sample_step=1.0),
            file_size=0,
            date_modified=0.0,
        )

        widget = ProfileWidget()
        try:
            widget.stats_widget.update_data(([0.0, 1.0], [1.0, 2.0]))

            widget.update_plot([profile], "empty-dir")

            self.assertTrue(widget.canvas.isHidden())
            self.assertTrue(widget.toolbar.isHidden())
            self.assertFalse(widget.stats_widget.isHidden())
            self.assertFalse(widget.empty_state_label.isHidden())
            self.assertEqual(widget.empty_state_label.text(), "No profiles in selected folder")
            self.assertEqual(widget.figure.axes, [])
            for stat_widget in widget.stats_widget.widgets:
                self.assertIsNone(stat_widget.value)
                self.assertEqual(stat_widget.value_label.text(), MISSING)
        finally:
            destroy(widget)

    def test_update_plot_with_empty_profile_data_shows_message_and_resets_stats(self):
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

        widget = ProfileWidget()
        try:
            widget.stats_widget.update_data(([0.0, 1.0], [1.0, 2.0]))

            widget.update_plot([profile], "empty-dir")

            self.assertTrue(widget.canvas.isHidden())
            self.assertTrue(widget.toolbar.isHidden())
            self.assertFalse(widget.stats_widget.isHidden())
            self.assertFalse(widget.empty_state_label.isHidden())
            self.assertEqual(widget.empty_state_label.text(), "No profiles in selected folder")
            self.assertEqual(widget.figure.axes, [])
            for stat_widget in widget.stats_widget.widgets:
                self.assertIsNone(stat_widget.value)
                self.assertEqual(stat_widget.value_label.text(), MISSING)
        finally:
            destroy(widget)

    def test_update_plot_with_no_profiles_shows_message_and_placeholder_stats(self):
        widget = ProfileWidget()
        try:
            widget.stats_widget.update_data(([0.0, 1.0], [1.0, 2.0]))

            widget.update_plot([], "empty-dir")

            self.assertTrue(widget.canvas.isHidden())
            self.assertFalse(widget.stats_widget.isHidden())
            self.assertFalse(widget.empty_state_label.isHidden())
            self.assertEqual(widget.empty_state_label.text(), "No profiles in selected folder")
            for stat_widget in widget.stats_widget.widgets:
                self.assertIsNone(stat_widget.value)
                self.assertEqual(stat_widget.value_label.text(), MISSING)
        finally:
            destroy(widget)

    def test_a_scan_shorter_than_the_analysis_window_draws_quietly(self):
        """A short roll is a short roll, not a fault.

        scipy shortens the spectrum window to the data it was given and warns
        while doing it, which reads as though the measurement were wrong.
        """
        original_show_spectrum = preferences.show_spectrum
        preferences.show_spectrum = True
        widget = ProfileWidget()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                widget.update_plot(_synthetic_profiles(1), "roll")

            self.assertEqual([str(warning.message) for warning in caught], [])
        finally:
            preferences.show_spectrum = original_show_spectrum
            destroy(widget)

    def test_an_empty_chart_draws_quietly(self):
        """With nothing ticked the y limits come out flat, which is not a limit.

        The pair was handed to matplotlib anyway, which warned about a singular
        transformation over a chart that is empty because that is what was asked
        for.
        """
        original_recalculate = preferences.recalculate_mean
        preferences.recalculate_mean = True
        widget = ProfileWidget()
        try:
            profiles = _synthetic_profiles(3)
            for profile in profiles:
                profile.hidden = True

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                widget.update_plot(profiles, "roll")

            self.assertEqual([str(warning.message) for warning in caught], [])
            low, high = widget.profile_ax.get_ylim()
            self.assertLess(low, high)
        finally:
            preferences.recalculate_mean = original_recalculate
            destroy(widget)


if __name__ == "__main__":
    unittest.main()


class TestLocalSettingsOverrides(unittest.TestCase):
    """settings.py is an installation's override file, so what it holds must act.

    Both line widths were consumed before the design system landed and silently
    stopped being read when the chart moved onto the system's mark weights —
    while the colour beside them kept working, which is the combination most
    likely to waste somebody's afternoon.
    """

    def test_the_mean_profile_honours_a_local_line_width(self):
        from unittest.mock import patch

        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        from theme import mpl as tapio_mpl

        figure = Figure()
        ax = figure.add_subplot(111)
        with patch.object(settings, "MEAN_PROFILE_LINE_WIDTH", 7.5):
            line = tapio_mpl.profile(
                ax, [0, 1, 2], [1, 2, 3],
                width=settings.MEAN_PROFILE_LINE_WIDTH,
            )[-1]
        self.assertEqual(line.get_linewidth(), 7.5)

        # None means the system's own weight, as the colour beside it does.
        line = tapio_mpl.profile(ax, [0, 1, 2], [1, 2, 3], width=None)[-1]
        self.assertEqual(line.get_linewidth(), tapio_mpl.mark("series"))

    def test_unticking_every_profile_is_not_an_error(self):
        """The chart is empty because that is what was asked for.

        It used to answer an empty selection with the amber warning about
        profiles being too short to average, which says something is wrong
        with the measurement when nothing is.
        """
        from utils.translation import _

        original_recalculate = preferences.recalculate_mean
        preferences.recalculate_mean = True
        widget = ProfileWidget()
        try:
            profiles = _synthetic_profiles(3)
            for profile in profiles:
                profile.hidden = True
            widget.update_plot(profiles, "roll")

            self.assertEqual(
                widget.warning_label.accessibleName(),
                _("CHART_NOTE_NO_PROFILES_SELECTED"),
            )
            self.assertEqual(widget.warning_label.property("banner"), "info")
        finally:
            preferences.recalculate_mean = original_recalculate
            widget.deleteLater()

    def test_profiles_too_short_to_average_still_warn(self):
        from utils.translation import _

        widget = ProfileWidget()
        try:
            # There are profiles; they just cannot be averaged — which is the
            # case the amber warning is actually for.
            with patch("gui.widgets.ProfileWidget.calc_mean_profile",
                       return_value=([], [])):
                widget.update_plot(_synthetic_profiles(1), "roll")

            self.assertEqual(
                widget.warning_label.accessibleName(),
                _("CHART_WARNING_TEXT_TOO_SHORT_PROFILES"),
            )
            self.assertEqual(widget.warning_label.property("banner"), "warn")
        finally:
            widget.deleteLater()

    def test_the_spectrum_is_a_line_and_not_an_area(self):
        """A wash under a spectrum reads as magnitude over a band.

        A peak at one wavelength is not that, and the shading sat under every
        line in the panel whether or not there was anything to weigh.
        """
        from matplotlib.collections import PolyCollection

        original_show_spectrum = preferences.show_spectrum
        preferences.show_spectrum = True
        widget = ProfileWidget()
        try:
            widget.update_plot(_synthetic_profiles(1), "roll")
            self.assertEqual(
                [artist for artist in widget.spectrum_ax.collections
                 if isinstance(artist, PolyCollection)],
                [],
            )
            self.assertTrue(widget.spectrum_ax.lines)
        finally:
            preferences.show_spectrum = original_show_spectrum
            widget.deleteLater()

    def test_the_distance_axis_is_subdivided_by_marks_not_by_rules(self):
        """Finer intervals belong on the axis, not across the profiles.

        A minor grid over a stack of profiles is texture rather than
        information, so the subdivisions are tick marks only.
        """
        from theme import mpl as tapio_mpl

        widget = ProfileWidget()
        try:
            widget.update_plot(_synthetic_profiles(3), "roll")
            axis = widget.profile_ax.xaxis

            minor = axis.get_minor_ticks()
            self.assertTrue(minor)
            self.assertTrue(all(tick.tick1line.get_visible() for tick in minor))
            self.assertTrue(
                all(tick.tick1line.get_markersize() == tapio_mpl.MINOR_TICK_SIZE
                    for tick in minor)
            )
            self.assertFalse(any(tick.gridline.get_visible() for tick in minor))
        finally:
            widget.deleteLater()

    def test_every_profile_behind_the_mean_is_drawn_the_same(self):
        """They are context, not a series, so none of them is lighter than another.

        They used to step down an ordinal ramp by age, which read as several
        different kinds of line on a chart whose subject is the mean.
        """
        from theme import mpl as tapio_mpl

        widget = ProfileWidget()
        try:
            widget.update_plot(_synthetic_profiles(5), "roll")

            supporting = [
                line for line in widget.profile_ax.lines
                if line.get_linewidth() == tapio_mpl.supporting_width()
            ]
            self.assertEqual(len(supporting), 5)
            self.assertEqual(
                {line.get_color() for line in supporting},
                {tapio_mpl.supporting_color(widget.tokens)[0]},
            )
            self.assertEqual({line.get_alpha() for line in supporting}, {tapio_mpl.SUPPORTING_ALPHA})
        finally:
            widget.deleteLater()

    def test_a_selected_profile_honours_a_local_line_width(self):
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        from theme import mpl as tapio_mpl

        figure = Figure()
        ax = figure.add_subplot(111)

        selected = tapio_mpl.supporting(
            ax, [0, 1], [1, 2], color="#1E73BE", selected=True, selected_width=6.0
        )
        self.assertEqual(selected.get_linewidth(), 6.0)

        # The unselected ones stay recessive whatever the override says; that is
        # what keeps the mean readable over them.
        other = tapio_mpl.supporting(
            ax, [0, 1], [1, 2], color="#1E73BE", selected=False, selected_width=6.0
        )
        self.assertEqual(other.get_linewidth(), tapio_mpl.supporting_width())


class TestPlotToolbar(unittest.TestCase):
    """The navigation bar's icons follow the theme.

    Matplotlib bakes each icon at construction — it masks the black glyph and
    refills it with the foreground colour, but only when the palette it sees at
    that moment is dark — and never looks again. Left alone, a bar built in
    light keeps black icons on the dark theme's near-black ground.

    This also pins the two private attributes the re-tint reads
    (``_actions``, ``_icon``): if a matplotlib upgrade moves them, the icons go
    back to not updating, and it should be this that says so.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import theme
        from theme import qt as theme_qt

        self._restore = theme_qt.tokens().theme
        theme.apply(self.app, theme="light")
        self.widget = ProfileWidget()

    def tearDown(self):
        import theme
        from test.qtcleanup import destroy

        destroy(self.widget)
        theme.apply(self.app, theme=self._restore)

    @staticmethod
    def _ink(action):
        """The average colour of an icon's opaque pixels."""
        image = action.icon().pixmap(24, 24).toImage()
        total, count = [0, 0, 0], 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > 100:
                    total[0] += pixel.red()
                    total[1] += pixel.green()
                    total[2] += pixel.blue()
                    count += 1
        return tuple(channel // count for channel in total) if count else None

    def test_the_toolbar_knows_what_its_icons_were_drawn_from(self):
        self.assertTrue(
            self.widget.toolbar._icon_files,
            "matplotlib's action map has moved; the icons will stop re-tinting",
        )

    def test_the_icons_follow_the_theme(self):
        import theme

        action = next(iter(self.widget.toolbar._icon_files))

        in_light = self._ink(action)
        self.assertIsNotNone(in_light)

        theme.apply(self.app, theme="dark")
        self.app.processEvents()
        in_dark = self._ink(action)

        self.assertNotEqual(
            in_light, in_dark,
            "the toolbar icons did not change with the theme",
        )
        # Dark ground wants light glyphs, and light ground dark ones.
        self.assertGreater(sum(in_dark), sum(in_light))

        theme.apply(self.app, theme="light")
        self.app.processEvents()
        self.assertEqual(self._ink(action), in_light)
