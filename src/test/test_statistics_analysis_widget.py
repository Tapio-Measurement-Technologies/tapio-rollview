import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock

from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget


class TestStatisticsAnalysisWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_point_selection_highlights_clicked_bar_and_emits_directory(self):
        widget = StatisticsAnalysisWidget()
        try:
            widget.chart.highlight_point = MagicMock()
            emitted_paths = []
            widget.directory_selected.connect(emitted_paths.append)

            widget.on_point_selected("/tmp/roll-a")

            widget.chart.highlight_point.assert_called_once_with("roll-a")
            self.assertEqual(emitted_paths, ["/tmp/roll-a"])
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
