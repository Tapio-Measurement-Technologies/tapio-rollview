import os
import re
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.colors import to_rgba
from PySide6.QtWidgets import QApplication

from gui.widgets.StatisticsAnalysis import StatisticsAnalysisChart, StatisticsAnalysisWidget
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
            chart.close()

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
            chart.close()

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
            self.assertEqual(chart.bars[1].get_facecolor(), to_rgba("tab:orange"))
        finally:
            chart.close()


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
            widget.close()

    def test_roll_filter_change_does_not_start_statistics_processor(self):
        widget = StatisticsAnalysisWidget()
        try:
            widget.cache_valid = False
            widget.processor.start = MagicMock()

            widget.set_roll_filter("roll", re.compile(r"roll", re.IGNORECASE))

            widget.processor.start.assert_not_called()
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
