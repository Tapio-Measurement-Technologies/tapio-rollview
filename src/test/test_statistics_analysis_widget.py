import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock

from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget
from test.qtcleanup import destroy


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
            # close() only hides it. Left for the cyclic collector, this tree
            # is torn down with Python and Qt both believing they own the
            # canvas inside it, and the second free takes the process with it.
            destroy(widget)


if __name__ == "__main__":
    unittest.main()
