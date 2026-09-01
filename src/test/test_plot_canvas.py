"""The canvas that holds its render back until a resize settles.

These guard things that are easy to undo by accident and obvious only on a real
screen: the colour of the strip Qt paints while a render is outstanding, the
colour of a canvas that has never rendered at all, and the fact that the canvas
does not chase every resize event.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.figure import Figure
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, Qt
from PySide6.QtWidgets import QApplication

import theme
from gui.widgets.PlotCanvas import PlotCanvas
from theme import mpl as tapio_mpl
from theme import tokens as T
from test.qtcleanup import destroy


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

    def test_the_plot_stays_on_screen_through_a_resize(self):
        """A deferred render must not mean an empty panel.

        Matplotlib blits its buffer at the buffer's own size, so once the widget
        and the buffer disagree it paints nothing at all — the plot vanishes for
        the length of a drag. The previous frame is stretched over the new size
        instead, so the shape of the data stays visible the whole way.
        """
        axes = self.canvas.figure.axes[0]
        axes.plot([0, 1, 2], [0, 1, 0], color="#FF00FF", linewidth=6)
        self.canvas.draw()
        self._settle()

        self.canvas.resize(700, 500)
        self.app.processEvents()   # paint, but do not wait for the settle timer

        image = self.canvas.grab().toImage()
        colours = {
            _hex(image.pixelColor(x, y))
            for x in range(0, 700, 7) for y in range(0, 500, 7)
        }
        self.assertIn("#FF00FF", colours, "the plotted line disappeared on resize")

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

    def _unrendered_canvas(self, unready_ms=None):
        """A canvas as it is between construction and its first render."""
        canvas = PlotCanvas(Figure())
        self.addCleanup(destroy, canvas)
        if unready_ms is not None:
            canvas.UNREADY_MS = unready_ms
        tapio_mpl.restyle_figure(canvas.figure)
        canvas.sync_background()
        canvas.resize(400, 300)
        canvas.show()
        self._settle()
        self.assertIsNone(canvas._last_frame, "the canvas rendered before it was asked to")
        return canvas

    def _middle_band(self, canvas):
        """The colours across the middle of the canvas, where a line would be."""
        image = canvas.grab().toImage()
        return {_hex(image.pixelColor(x, y)).upper()
                for x in range(0, 400, 2) for y in range(140, 160)}

    def test_a_canvas_that_has_never_rendered_is_the_figure_colour(self):
        """Not black, which is what a Windows build showed at startup.

        Matplotlib declares the canvas opaque - Qt then paints nothing under it
        - and paints nothing itself until a render exists, so the plot area was
        whatever the window arrived with for as long as the first render took.
        """
        canvas = self._unrendered_canvas()

        sampled = _hex(canvas.grab().toImage().pixelColor(200, 150))

        self.assertEqual(sampled.upper(),
                         tapio_mpl.current.color("surface").upper())

    def test_a_short_wait_is_a_blank_panel_and_nothing_else(self):
        """A chart that arrives promptly must not flash a message on the way."""
        canvas = self._unrendered_canvas()

        self.assertEqual(self._middle_band(canvas),
                         {tapio_mpl.current.color("surface").upper()})

    def test_a_wait_that_runs_on_says_it_is_loading(self):
        """A blank panel is fine for a moment and looks broken after that."""
        canvas = self._unrendered_canvas(unready_ms=0)
        self._settle()

        band = self._middle_band(canvas)
        # Text on the panel, rather than a panel of some other colour.
        self.assertIn(tapio_mpl.current.color("surface").upper(), band)
        self.assertGreater(len(band), 1, "the panel said nothing while it waited")

    def test_the_first_frame_gives_the_canvas_its_opacity_back(self):
        """The background fill is for the wait, not for every frame after it."""
        canvas = self._unrendered_canvas()
        self.assertFalse(
            canvas.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent))

        canvas.figure.add_subplot(111)
        canvas.draw()

        self.assertTrue(
            canvas.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent))

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
