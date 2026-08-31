import unittest
import numpy as np
from PySide6.QtWidgets import QApplication, QLabel
from gui.widgets.stats import StatsWidget, MeanWidget, StdWidget, CVWidget, MinWidget, MaxWidget, PeakToPeakWidget, SlopeWidget
from utils import preferences
from utils.translation import _
import settings
import theme
from test.qtcleanup import destroy

class TestStatWidgets(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_NONE
        preferences.excluded_regions = ""
        self.data = np.array([1, 2, 3, 4, 5])
        self.limits = {
            "mean_g": {'name': 'mean_g', 'min': 1.0, 'max': 5.0},
            "stdev_g": {'name': 'stdev_g', 'min': 0.5, 'max': 2.0},
            "cv_pct": {'name': 'cv_pct', 'min': 10.0, 'max': 50.0},
            "min_g": {'name': 'min_g', 'min': 0.1, 'max': 1.5},
            "max_g": {'name': 'max_g', 'min': 4.5, 'max': 5.0},
            "pp_g": {'name': 'pp_g', 'min': 3.0, 'max': 4.9},
            "slope_g_per_rl": {'name': 'slope_g_per_rl', 'min': -10.0, 'max': 10.0}
        }

    def tearDown(self):
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions

    def test_mean_widget_initialization(self):
        widget = MeanWidget(self.data)
        self.assertAlmostEqual(widget.value, np.mean(self.data))
        self.assertEqual(widget.value_label.text(), f"{np.mean(self.data):.1f}")

    def test_the_tile_guidance_names_it_its_limits_and_the_click(self):
        widget = MeanWidget(self.data, limit=self.limits['mean_g'])
        guidance = widget.statusTip()
        self.assertIn(widget.name, guidance)
        # The same words as the footer under the number, not a second wording
        # of the same two bounds.
        self.assertIn(widget.foot_label.text(), guidance)
        self.assertIn(_("GUIDANCE_EDIT_ALERT_LIMITS"), guidance)

    def test_every_part_of_the_tile_answers_a_hover(self):
        # Qt emits the status tip of the widget the pointer entered and asks no
        # parent for one, so the line has to be on every label as well — the
        # number and the limit line cover most of the tile.
        widget = MeanWidget(self.data, limit=self.limits['mean_g'])
        parts = [
            widget.label,
            widget.value_label,
            widget.unit_label,
            widget.foot_label,
            widget.foot_label.min_chunk,
            widget.foot_label.max_chunk,
        ]
        for part in parts:
            with self.subTest(part=part.__class__.__name__):
                self.assertEqual(part.statusTip(), widget.statusTip())

    def test_a_squeezed_limit_line_is_still_readable_somewhere(self):
        """A narrow tile elides its limit line; the guidance must not.

        The row at the foot of the window has room a 120 px tile never will, so
        it is where both bounds stay legible when the footer is cut to "≥ 1.0,".
        """
        widget = MeanWidget(self.data, limit=self.limits['mean_g'])
        chunk = widget.foot_label.min_chunk
        # setText re-elides against the width the chunk has now, which is the
        # same path a splitter drag takes through resizeEvent.
        chunk.setFixedWidth(12)
        chunk.setText(chunk.text())

        # Painted short, still whole underneath: this is the elided case.
        self.assertNotEqual(QLabel.text(chunk), chunk.text())
        # Nothing pops up over the cut text; the row carries both bounds.
        self.assertEqual(chunk.toolTip(), "")
        self.assertEqual(chunk.statusTip(), widget.statusTip())
        self.assertIn("5.0", widget.statusTip())
        self.assertIn(_("GUIDANCE_EDIT_ALERT_LIMITS"), widget.statusTip())

    def test_no_part_of_the_tile_pops_anything_up(self):
        """Guidance goes in the row at the foot; nothing hovers over the data."""
        widget = MeanWidget(self.data, limit=self.limits['mean_g'])
        parts = [widget, widget.label, widget.value_label, widget.unit_label,
                 widget.foot_label, widget.foot_label.min_chunk,
                 widget.foot_label.max_chunk]
        for part in parts:
            with self.subTest(part=part.__class__.__name__):
                self.assertEqual(part.toolTip(), "")

    def test_stat_widget_without_limits_still_offers_the_editor(self):
        # The tile with nothing configured is the one an operator most needs
        # told that a click is what configures it.
        widget = MeanWidget(self.data)
        guidance = widget.statusTip()
        self.assertIn(_("ALERT_LIMITS_NOT_SET"), guidance)
        self.assertIn(_("GUIDANCE_EDIT_ALERT_LIMITS"), guidance)

    def test_stat_widget_limit_exceeded(self):
        # The tile does not carry its own colour: it sets the `state` property
        # and the theme's style sheet owns what red looks like. Only the failing
        # tile gets the state, so a row of tiles still says which one failed.
        widget = MaxWidget(self.data, limit=self.limits['max_g'])
        widget.update_data([7.0])
        self.assertTrue(widget.over_limit)
        self.assertEqual(widget.property("state"), theme.STATUS_BAD)
        self.assertEqual(widget.value_label.property("state"), theme.STATUS_BAD)

    def test_stat_widget_within_limit_carries_no_state(self):
        # max_g is configured 4.5-5.0, so 4.8 is inside both ends.
        widget = MaxWidget(self.data, limit=self.limits['max_g'])
        widget.update_data([4.8])
        self.assertFalse(widget.over_limit)
        self.assertIsNone(widget.property("state"))

    def test_stat_widget_states_the_limit_under_the_number(self):
        # Not hover-only: on a mill-floor tablet there is no hover, so the limit
        # is on the tile. It reads the same whatever the value did — a footer
        # that switches vocabulary under load takes away the number the
        # operator is being measured against.
        widget = MaxWidget(self.data, limit=self.limits['max_g'])

        widget.update_data([4.8])
        self.assertEqual(widget.foot_label.text(), "\u2265 4.5, \u2264 5.0")
        self.assertIsNone(widget.foot_label.min_chunk.property("limit"))
        self.assertIsNone(widget.foot_label.max_chunk.property("limit"))

        widget.update_data([7.0])
        self.assertEqual(widget.foot_label.text(), "\u2265 4.5, \u2264 5.0")
        self.assertEqual(widget.foot_label.max_chunk.property("limit"), "breached")
        self.assertIsNone(widget.foot_label.min_chunk.property("limit"))

        widget.update_data([1.0])
        self.assertEqual(widget.foot_label.min_chunk.property("limit"), "breached")
        self.assertIsNone(widget.foot_label.max_chunk.property("limit"))

    def test_stat_widget_with_one_bound_states_only_that_bound(self):
        widget = MaxWidget(self.data, limit={'name': 'max_g', 'min': 4.5, 'max': None})
        self.assertEqual(widget.foot_label.text(), "\u2265 4.5")
        self.assertFalse(widget.foot_label.max_chunk.isVisible())

    def test_a_long_limit_never_widens_the_tile(self):
        """Seven statistics have to fit across one row; the footer elides.

        The chunked footer is the one that could break this — a plain QLabel
        would demand the width of its text and push the row onto two lines.
        """
        plain = MeanWidget(self.data)
        wide = MeanWidget(self.data, limit={'name': 'mean_g', 'min': -123456.75, 'max': 987654.25})
        self.assertEqual(wide.content_width(), plain.content_width())
        self.assertEqual(wide.foot_label.min_chunk.minimumSizeHint().width(), 0)

    def test_editing_one_tile_re_judges_the_whole_run(self):
        """The verdict belongs to the run, not to the tile that was edited.

        The tile that opens the editor refreshes itself; without this the run's
        verdict — and so the object bar at the top of the window — kept the old
        answer until the operator changed folder.
        """
        widget = StatsWidget(self.data)
        try:
            verdicts = []
            widget.verdict_changed.connect(verdicts.append)
            limits = [dict(limit) for limit in preferences.alert_limits]
            for limit in limits:
                limit['min'] = None
                limit['max'] = 0.5 if limit['name'] == 'max_g' else None
            preferences.update_preferences({'alert_limits': limits})

            tile = next(w for w in widget.widgets if w.func.name == 'max_g')
            tile.limit = next(
                l for l in preferences.alert_limits if l['name'] == 'max_g'
            )
            tile.update_data(tile.data)
            tile.limit_edited.emit()

            self.assertEqual(widget.verdict(), theme.STATUS_BAD)
            self.assertEqual(verdicts[-1], theme.STATUS_BAD)
        finally:
            destroy(widget)

    def test_stat_widget_without_limits_says_so(self):
        # An em dash, and the same shape as a tile that has limits: seven tiles
        # each spelling out a sentence about having none was the noise, and the
        # word "Limits" in front of every one of them was the next layer of it.
        widget = MeanWidget(self.data)
        self.assertEqual(widget.foot_label.text(), "\u2014")

    def test_stat_widget_without_data_shows_em_dash(self):
        # Missing is an em dash, not 0, not blank, not NaN. Zero is a measurement.
        widget = MeanWidget(self.data)
        widget.update_data([])
        self.assertIsNone(widget.value)
        self.assertEqual(widget.value_label.text(), "\u2014")

    def test_stats_widget_initialization(self):
        widget = StatsWidget(self.data)
        for stat_widget in widget.widgets:
            self.assertTrue(np.array_equal(stat_widget.data, self.data))

    def test_update_data(self):
        widget = StatsWidget(self.data)
        new_data = np.array([10, 20, 30, 40, 50])
        widget.update_data(new_data)
        for stat_widget in widget.widgets:
            self.assertTrue(np.array_equal(stat_widget.data, new_data))

    def test_mean_widget(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        self.assertEqual(widget.value, np.mean(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([6.0])
        self.assertTrue(widget.over_limit)

    def test_mean_widget_below_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([0.5, 0.5, 0.5])
        self.assertTrue(widget.over_limit)

    def test_mean_widget_at_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertFalse(widget.over_limit)

    def test_mean_widget_above_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([6.0, 7.0, 8.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        self.assertEqual(widget.value, np.std(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget_below_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget_at_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertFalse(widget.over_limit)

    def test_stdev_widget_above_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 5.0, 9.0, 13.0, 17.0])
        self.assertTrue(widget.over_limit)

    def test_cv_widget(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        self.assertEqual(widget.value, (np.std(self.data) / np.mean(self.data)) * 100)
        self.assertFalse(widget.over_limit)

        widget.update_data([0.1, 0.2, 0.3, 0.4, 100])
        self.assertTrue(widget.over_limit)

    def test_cv_widget_below_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_cv_widget_at_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertFalse(widget.over_limit)

    def test_cv_widget_above_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([1.0, 100.0, 200.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        self.assertEqual(widget.value, np.min(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([0.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget_below_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([0.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget_at_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([0.1, 0.2, 0.3])
        self.assertFalse(widget.over_limit)

    def test_min_widget_above_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([2.0, 3.0, 4.0])
        self.assertTrue(widget.over_limit)

    def test_max_widget(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        self.assertEqual(widget.value, np.max(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([7.0])
        self.assertTrue(widget.over_limit)

    def test_max_widget_below_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([4.0, 4.4])
        self.assertTrue(widget.over_limit)

    def test_max_widget_at_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([4.5, 5.0])
        self.assertFalse(widget.over_limit)

    def test_max_widget_above_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([5.5, 6.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        self.assertEqual(widget.value, np.max(self.data) - np.min(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([10.0, 15.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget_below_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 2.0, 3.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget_at_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 4.0])
        self.assertFalse(widget.over_limit)

    def test_peak_to_peak_widget_above_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 6.0])
        self.assertTrue(widget.over_limit)

    def test_slope_widget(self):
        linear_data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        expected_slope = 4.0

        widget = SlopeWidget(linear_data, self.limits['slope_g_per_rl'])
        self.assertAlmostEqual(widget.value, expected_slope)
        self.assertFalse(widget.over_limit)

    def test_slope_widget_with_flat_profile(self):
        flat_data = np.array([3.0, 3.0, 3.0, 3.0])

        widget = SlopeWidget(flat_data, self.limits['slope_g_per_rl'])
        self.assertAlmostEqual(widget.value, 0.0)
        self.assertFalse(widget.over_limit)

    def test_slope_widget_is_length_normalized(self):
        short_linear = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        long_linear = np.linspace(1.0, 5.0, 17)

        short_widget = SlopeWidget(short_linear, self.limits['slope_g_per_rl'])
        long_widget = SlopeWidget(long_linear, self.limits['slope_g_per_rl'])

        self.assertAlmostEqual(short_widget.value, long_widget.value)

if __name__ == "__main__":
    unittest.main()
