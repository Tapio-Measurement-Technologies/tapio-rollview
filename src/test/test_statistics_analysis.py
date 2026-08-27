import os
import re
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.colors import to_rgba
from matplotlib.patches import Rectangle
from theme import mpl as tapio_mpl
from theme import tokens as T
from PySide6.QtWidgets import QApplication

from gui.widgets.StatisticsAnalysis import StatisticsAnalysisChart, StatisticsAnalysisWidget
from test.qtcleanup import destroy
from utils import preferences, profile_stats
from utils.translation import _


class TestStatisticsAnalysisChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_plot_without_data_shows_message_outside_plot(self):
        chart = StatisticsAnalysisChart()
        try:
            chart.plot([])

            self.assertTrue(chart.canvas.isHidden())
            self.assertFalse(chart.empty_state_label.isHidden())
            self.assertEqual(chart.empty_state_label.text(), _("NO_DATA_AVAILABLE"))
            self.assertEqual(len(chart.bars), 0)
            axis_texts = [text.get_text() for text in chart.ax.texts]
            self.assertNotIn(_("NO_DATA_AVAILABLE"), axis_texts)
        finally:
            destroy(chart)

    def test_plot_with_data_restores_canvas_after_empty_state(self):
        chart = StatisticsAnalysisChart()
        try:
            chart.plot([])
            chart.plot([
                {"x": 1, "y": 10.0, "label": "roll-1", "path": "/tmp/roll-1"},
            ])

            self.assertFalse(chart.canvas.isHidden())
            self.assertTrue(chart.empty_state_label.isHidden())
            self.assertEqual(chart.empty_state_label.text(), "")
            self.assertEqual(len(chart.bars), 1)
        finally:
            destroy(chart)

    def test_pick_selects_clicked_bar_and_emits_directory_path(self):
        chart = StatisticsAnalysisChart()
        try:
            emitted_paths = []
            chart.point_selected.connect(emitted_paths.append)
            chart.plot([
                {"x": 1, "y": 10.0, "label": "roll-1", "path": "/tmp/roll-1"},
                {"x": 2, "y": 20.0, "label": "roll-2", "path": "/tmp/roll-2"},
            ])

            chart.on_pick(SimpleNamespace(artist=chart.bars[1]))

            self.assertEqual(emitted_paths, ["/tmp/roll-2"])
            self.assertEqual(chart.highlighted_point, "roll-2")
            # Selection is a state laid over identity: the bar keeps its hue and
            # steps toward the ink, so a failing bar still reads as failing.
            t = tapio_mpl.current
            self.assertEqual(
                chart.bars[1].get_facecolor(),
                to_rgba(T.mix(t.color("ink"), t.recency[0], 0.35)),
            )
            self.assertEqual(
                chart.bars[0].get_facecolor(),
                to_rgba(t.recency[0]),
            )
            # And it is a fill, not an outline: the two used to disagree.
            self.assertEqual(chart.bars[1].get_linewidth(), chart.bars[0].get_linewidth())
        finally:
            destroy(chart)

    def test_a_failing_bar_keeps_its_status_when_selected(self):
        """The selected bar must not stop looking like a violation."""
        chart = StatisticsAnalysisChart()
        try:
            chart.parent_widget = SimpleNamespace(selected_stat="mean")
            alert_name = profile_stats.analysis_to_alert_name["mean"]
            original = preferences.alert_limits
            preferences.alert_limits = [{"name": alert_name, "min": None, "max": 15.0}]
            try:
                chart.plot([
                    {"x": 1, "y": 10.0, "label": "roll-1", "path": "/tmp/roll-1"},
                    {"x": 2, "y": 99.0, "label": "roll-2", "path": "/tmp/roll-2"},
                ])
                chart.highlight_point("roll-2")

                t = tapio_mpl.current
                self.assertEqual(
                    chart.bars[1].get_facecolor(),
                    to_rgba(T.mix(t.color("ink"), t.chart("limit"), 0.35)),
                )
            finally:
                preferences.alert_limits = original
        finally:
            destroy(chart)

    def test_the_out_of_limit_region_is_hatched_not_flooded(self):
        """A flat tint strong enough to see swamps a panel this far out of range.

        The region beyond a limit is most of the frame when a statistic ranges
        well past it, so it carries the same diagonal the profile chart uses for
        an excluded region — the vocabulary for "this does not count" — at the
        sparser of the two densities, because hatch reads by how much of a
        region it inks.
        """
        chart = StatisticsAnalysisChart()
        try:
            chart.parent_widget = SimpleNamespace(selected_stat="mean")
            alert_name = profile_stats.analysis_to_alert_name["mean"]
            original = preferences.alert_limits
            preferences.alert_limits = [{"name": alert_name, "min": None, "max": 15.0}]
            try:
                chart.plot([
                    {"x": 1, "y": 99.0, "label": "roll-1", "path": "/tmp/roll-1"},
                ])
                washes = [a for a in chart.ax.get_children()
                          if isinstance(a, Rectangle) and a.get_hatch()]
                self.assertEqual(len(washes), 1)
                self.assertEqual(washes[0].get_hatch(), tapio_mpl.WIDE_HATCH)
                # Under everything, including the gridlines.
                for bar in chart.bars:
                    self.assertLess(washes[0].get_zorder(), bar.get_zorder())
            finally:
                preferences.alert_limits = original
        finally:
            destroy(chart)

    def test_the_limit_line_sits_behind_the_bars(self):
        """Two marks in the same hex are one mark — unless they never overlap.

        The line is the limit red, the same red a failing bar is filled with,
        which on top of the bars made it vanish wherever it crossed one. Colour
        was the wrong lever: it belongs behind them, on the ground the data
        stands on. Above the gridlines, below every bar.
        """
        chart = StatisticsAnalysisChart()
        try:
            chart.parent_widget = SimpleNamespace(selected_stat="mean")
            alert_name = profile_stats.analysis_to_alert_name["mean"]
            original = preferences.alert_limits
            preferences.alert_limits = [{"name": alert_name, "min": 5.0, "max": 15.0}]
            try:
                chart.plot([
                    {"x": 1, "y": 99.0, "label": "roll-1", "path": "/tmp/roll-1"},
                ])
                t = tapio_mpl.current
                lines = [line for line in chart.ax.get_lines()
                         if line.get_linestyle() == "-"]
                self.assertEqual(len(lines), 2, "expected both limit lines")
                for line in lines:
                    # One step deeper on the red ramp than a failing bar's fill.
                    self.assertEqual(
                        to_rgba(line.get_color()),
                        to_rgba(tapio_mpl.limit_line_color(t)),
                    )
                    self.assertNotEqual(
                        to_rgba(line.get_color()), to_rgba(t.chart("limit"))
                    )
                    for bar in chart.bars:
                        self.assertLess(
                            line.get_zorder(), bar.get_zorder(),
                            "the limit line is drawn over the bars it judges",
                        )
            finally:
                preferences.alert_limits = original
        finally:
            destroy(chart)


class TestStatisticsAnalysisWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_apply_filters_combines_time_filter_and_roll_regex(self):
        widget = StatisticsAnalysisWidget()
        try:
            now = datetime.now().timestamp()
            old = (datetime.now() - timedelta(days=10)).timestamp()
            widget.set_roll_filter("roll-[13]", re.compile(r"roll-[13]", re.IGNORECASE))
            widget.filter_dropdown.setCurrentText(_("FILTER_LAST_7_DAYS"))

            filtered = widget.apply_filters([
                {"label": "roll-1", "timestamp": now, "stats": {}},
                {"label": "roll-2", "timestamp": now, "stats": {}},
                {"label": "roll-3", "timestamp": old, "stats": {}},
            ])

            self.assertEqual([roll["label"] for roll in filtered], ["roll-1"])
        finally:
            destroy(widget)

    def test_roll_filter_change_does_not_start_statistics_processor(self):
        widget = StatisticsAnalysisWidget()
        try:
            widget.cache_valid = False
            widget.processor.start = MagicMock()

            widget.set_roll_filter("roll", re.compile(r"roll", re.IGNORECASE))

            widget.processor.start.assert_not_called()
        finally:
            destroy(widget)


if __name__ == "__main__":
    unittest.main()
