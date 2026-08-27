import os
import re
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.colors import to_rgba
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

    def test_the_limit_line_is_not_the_colour_of_the_bars_it_judges(self):
        """Two marks in the same hex are one mark.

        The line used to be chart("limit"), the same red a failing bar is
        filled with, so it vanished wherever it crossed one.
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
                self.assertTrue(lines, "expected the limit lines to be drawn")
                for line in lines:
                    self.assertEqual(to_rgba(line.get_color()), to_rgba(t.color("ink")))
                    self.assertNotEqual(
                        to_rgba(line.get_color()), to_rgba(t.chart("limit"))
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
