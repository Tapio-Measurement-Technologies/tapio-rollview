# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""A Matplotlib canvas that re-renders once a resize has settled.

``FigureCanvasQTAgg.resizeEvent`` schedules a full Agg render of the figure, and
Qt delivers a resize event for every pixel of a splitter drag. An Agg pass over
a profile costs around 25 ms here, so dragging the sidebar asks for roughly
forty renders a second that each take longer than the frame they are for — which
is what made the window feel like it was dragging its heels.

The figure's *size* is still updated on every event, so geometry stays correct
and anything that measures the canvas gets the right answer. Only the render is
held back, and the last completed frame is stretched over the new size in the
meantime — Matplotlib's own paint path draws nothing at all once the buffer and
the widget disagree, which reads as the plot vanishing for the length of a drag.
A stretched plot is obviously provisional; an empty panel just looks broken.
"""

import weakref

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


class PlotCanvas(FigureCanvasQTAgg):
    """A canvas that reports when a resize has stopped instead of chasing it.

    Pass ``on_resize_settled`` — or set it afterwards — to re-run layout and
    redraw. Nothing is drawn automatically on resize; that callback is the whole
    contract.

    It is a plain callable and not a ``Signal`` on purpose. ``FigureCanvasQTAgg``
    inherits from both a QWidget and Matplotlib's own base, and declaring a new
    Signal on a class with that mix leaves PySide6 double-freeing the canvas
    when its parent is torn down. A callback needs none of that machinery.

    The callback is held *weakly*. It is nearly always a bound method of the
    widget this canvas sits in — which is also its Qt parent — and a strong
    reference the other way is a cycle through a C++ object that Python cannot
    collect, so the whole widget tree leaks.
    """

    #: How long to wait for the size to stop moving. Long enough to swallow a
    #: drag, short enough that letting go feels like an immediate redraw.
    SETTLE_MS = 60

    def __init__(self, figure, on_resize_settled=None):
        super().__init__(figure)
        self._on_resize_settled = None
        self.on_resize_settled = on_resize_settled
        self._suppress_idle_draw = False
        self._last_frame = None
        self._settle_timer = self._make_settle_timer()
        self.sync_background()

    def sync_background(self):
        """Paint the widget in the figure's own colour.

        While a resize is outstanding the rendered buffer is smaller than the
        widget, and Qt fills what the buffer does not cover with the widget's
        background — white by default. Against a dark chart that is a flash of
        white down the edge of every resize. Matching the widget to the figure
        makes the uncovered strip indistinguishable from the plot.

        Call it whenever the figure's face colour changes, which for RollView
        means whenever the theme does.
        """
        red, green, blue = (int(round(channel * 255))
                            for channel in self.figure.get_facecolor()[:3])
        color = QColor(red, green, blue)
        palette = self.palette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
            palette.setColor(role, color)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    @property
    def on_resize_settled(self):
        """The callback, or None if it was never set or has been collected."""
        if self._on_resize_settled is None:
            return None
        return self._on_resize_settled()

    @on_resize_settled.setter
    def on_resize_settled(self, callback):
        if callback is None:
            self._on_resize_settled = None
        elif hasattr(callback, "__self__"):
            self._on_resize_settled = weakref.WeakMethod(callback)
        else:
            self._on_resize_settled = weakref.ref(callback)

    def _make_settle_timer(self):
        """A timer owned by this canvas, or None when there is no GUI thread.

        The plot_export postprocessor builds a figure on a worker thread to
        render it once and save it. A QTimer may only be stopped on the thread
        that created it, and that path has no event loop to defer into anyway,
        so there it renders on the spot.
        """
        application = QApplication.instance()
        if application is None or QThread.currentThread() is not application.thread():
            return None
        # Deliberately unparented. Handing a Python-created QTimer to the
        # canvas as its Qt parent double-frees it when the canvas is collected
        # rather than explicitly deleted — Qt deletes the child and Python then
        # deletes it again. Holding it in an attribute means Python owns it
        # outright: it lives exactly as long as the canvas and is torn down once.
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self._notify_resize_settled)
        return timer

    def _notify_resize_settled(self):
        callback = self.on_resize_settled
        if callback is not None:
            callback()

    def resizeEvent(self, event):
        # Let Matplotlib do its geometry work — set_size_inches, the resize
        # callbacks — but swallow the draw it asks for at the end of it.
        self._suppress_idle_draw = True
        try:
            super().resizeEvent(event)
        finally:
            self._suppress_idle_draw = False
        self.sync_background()

        if self._settle_timer is None:
            self._notify_resize_settled()
            return
        self._settle_timer.start(self.SETTLE_MS)

    def draw_idle(self):
        if self._suppress_idle_draw:
            return
        super().draw_idle()

    def paintEvent(self, event):
        """Draw the last completed frame while a re-render is outstanding.

        Matplotlib blits its Agg buffer at the buffer's own size, so the moment
        the widget and the buffer disagree it paints nothing — the whole plot
        disappears until the resize settles. Stretching the previous frame over
        the new size keeps the shape of the data on screen throughout, and it is
        replaced by the real thing within a frame or two of the drag ending.
        """
        if self._resize_pending() and self._last_frame is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(self.rect(), self._last_frame)
            painter.end()
            return

        super().paintEvent(event)

    def draw(self):
        # Remember the frame here rather than in paintEvent: a render is what
        # produces a new frame, and a widget that is not on screen — under the
        # offscreen platform, or on a tab nobody has opened — may never be asked
        # to paint one.
        super().draw()
        self._remember_frame()

    def _resize_pending(self):
        return self._settle_timer is not None and self._settle_timer.isActive()

    def _remember_frame(self):
        """Keep a copy of what was just rendered, for the next resize."""
        try:
            buffer = np.asarray(self.buffer_rgba())
        except (AttributeError, RuntimeError, ValueError):
            # Nothing has been rendered yet; there is no frame to remember.
            return
        height, width = buffer.shape[:2]
        if not width or not height:
            return
        # .copy() detaches from the Agg buffer, which the next render overwrites.
        self._last_frame = QImage(
            buffer.data, width, height, QImage.Format.Format_RGBA8888
        ).copy()
