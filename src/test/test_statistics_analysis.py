import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.colors import to_rgba
from PySide6.QtWidgets import QApplication

from gui.widgets.StatisticsAnalysis import StatisticsAnalysisChart


class TestStatisticsAnalysisChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pick_selects_clicked_bar_and_emits_directory_path(self):
        chart = StatisticsAnalysisChart()
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


if __name__ == "__main__":
    unittest.main()
