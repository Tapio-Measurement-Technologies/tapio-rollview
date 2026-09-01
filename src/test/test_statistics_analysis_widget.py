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


class TestWaitingForContent(unittest.TestCase):
    """A panel with nothing in it yet is neither an error nor an empty state.

    It is the fourth pill's situation — no verdict yet — applied to a region
    instead of a value, and the system's rule for it is that a short wait says
    nothing at all. Most loads end inside the quiet window, and a "Loading..."
    that appears and disappears again reads as a fault rather than as speed.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_short_wait_is_never_announced(self):
        widget = StatisticsAnalysisWidget()
        try:
            widget.loading_widget.arm()
            self.assertIsNot(
                widget.stacked_widget.currentWidget(), widget.loading_widget,
                "the waiting page came up immediately",
            )
            widget.loading_widget.disarm()
            self.app.processEvents()
            self.assertIsNot(
                widget.stacked_widget.currentWidget(), widget.loading_widget
            )
        finally:
            destroy(widget)

    def test_a_wait_that_lasts_says_what_it_is_waiting_for(self):
        from PySide6.QtCore import QEventLoop, QTimer

        widget = StatisticsAnalysisWidget()
        try:
            widget.loading_widget.arm()

            loop = QEventLoop()
            widget.loading_widget.became_visible.connect(loop.quit)
            # Twice the quiet window, so a slow machine does not fail this.
            QTimer.singleShot(widget.loading_widget.QUIET_MS * 2, loop.quit)
            loop.exec()

            self.assertIs(
                widget.stacked_widget.currentWidget(), widget.loading_widget
            )
            # One line, and a bar because this wait can be counted. Nothing
            # spins: that motion is decoration, which the motion rules exclude.
            self.assertTrue(widget.loading_widget.loading_label.text())
            self.assertEqual(
                widget.loading_widget.loading_label.property("role"), "hint"
            )
        finally:
            destroy(widget)


class TestPanelsPaintTheirOwnSurface(unittest.TestCase):
    """A region owns its area the moment it exists.

    A Matplotlib canvas in Qt declares itself opaque and then draws nothing
    until its first render, which leaves the window's uninitialised background
    on screen — black, on Windows. The canvas paints the figure's own colour
    from construction so there is no frame in which that can happen.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_canvas_is_the_charts_colour_before_it_has_drawn(self):
        from PySide6.QtGui import QPalette
        from matplotlib.figure import Figure

        from gui.widgets.PlotCanvas import PlotCanvas
        from theme import mpl as tapio_mpl

        figure = Figure()
        figure.set_facecolor(tapio_mpl.current.color("surface"))
        canvas = PlotCanvas(figure)
        try:
            self.assertTrue(canvas.autoFillBackground())
            painted = canvas.palette().color(QPalette.ColorRole.Window).name()
            self.assertEqual(
                painted.upper(), tapio_mpl.current.color("surface").upper()
            )
        finally:
            destroy(canvas)


if __name__ == "__main__":
    unittest.main()
