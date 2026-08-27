"""The canvas that holds its render back until a resize settles.

Two of these guard things that are easy to undo by accident and obvious only on
a real screen: the colour of the strip Qt paints while a render is outstanding,
and the fact that the canvas does not chase every resize event.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.figure import Figure
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication

import theme
from gui.widgets.PlotCanvas import PlotCanvas
from theme import mpl as tapio_mpl
from theme import tokens as T


def _hex(color):
    return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"


class TestPlotCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        theme.apply(self.app, theme=T.DARK)
        self.canvas = PlotCanvas(Figure())
        tapio_mpl.restyle_figure(self.canvas.figure)
        self.canvas.sync_background()
        self.canvas.figure.add_subplot(111)
        self.canvas.resize(400, 300)
        self.canvas.show()
        # Render once, so there is a buffer for the resize to outgrow.
        self.canvas.draw()
        self._settle()

    def tearDown(self):
        self.canvas.close()
        self.canvas.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        theme.apply(self.app, theme=T.LIGHT)

    def _settle(self):
        for _ in range(5):
            self.app.processEvents()

    def test_the_uncovered_strip_is_the_figure_colour_not_white(self):
        """A resize must not flash the window background through the plot.

        While the render is outstanding the buffer is smaller than the widget,
        and Qt fills the difference with the widget's own background. Against
        the dark theme a default white one is a bar of white down the edge of
        every resize.
        """
        expected = tapio_mpl.current.color("surface")

        self.canvas.resize(700, 500)
        self.app.processEvents()   # paint, but do not wait for the settle timer

        image = self.canvas.grab().toImage()
        # Well inside the region the previous 400x300 buffer cannot cover.
        sampled = _hex(image.pixelColor(650, 200))
        self.assertEqual(sampled.upper(), expected.upper())

    def test_a_resize_does_not_render_immediately(self):
        """The whole point: forty resizes in a drag are not forty renders."""
        renders = []
        real_draw = self.canvas.draw
        self.canvas.draw = lambda *a, **k: (renders.append(1), real_draw(*a, **k))[1]
        try:
            for width in range(420, 460, 4):
                self.canvas.resize(width, 300)
                self.app.processEvents()
            self.assertEqual(renders, [])
        finally:
            self.canvas.draw = real_draw

    def test_the_settle_callback_is_held_weakly(self):
        """A strong reference from the canvas to its parent leaks the tree."""
        class Consumer:
            def on_settled(self):
                pass

        consumer = Consumer()
        self.canvas.on_resize_settled = consumer.on_settled
        self.assertIsNotNone(self.canvas.on_resize_settled)

        del consumer
        self.assertIsNone(self.canvas.on_resize_settled)


if __name__ == "__main__":
    unittest.main()
