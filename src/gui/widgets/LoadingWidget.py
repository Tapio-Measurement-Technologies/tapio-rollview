"""A panel that is waiting for its content.

Not an error, and not an empty state. It is the fourth status pill's situation —
no verdict yet — applied to a region instead of a value, and it is often the
first thing an operator sees.

The system's rules for it, and where each one lands here:

* **The panel paints its own surface from the first frame.** A region owns its
  area the moment it exists, whether or not it has anything to put in it yet.
  That one is not this widget's job — it belongs to whatever is behind it, and
  for the chart panels it is ``PlotCanvas.sync_background``.
* **Say nothing for the first 400 ms.** Most waits end inside that, and a
  message that appears and vanishes again is worse than the wait it described.
  ``QUIET_MS`` and ``arm()`` are that rule.
* **Then one line, centred, muted.** "Loading..." for content, or the verb where
  the wait has a name. No pill: a pill is a verdict about a measurement, and
  this is a statement about the screen.
* **Nothing in the panel simulates what is coming.** No skeleton, no shimmer:
  the layout has already reserved the space, so both mime the one thing they
  cannot supply. The test any animation has to pass is what the screen would
  lose if it stopped moving, and a shimmer over a placeholder loses nothing.

This wait *can* be counted — the processor reports how far through the folders
it is — so it gets the determinate bar with the number beside it. The other
case, a wait nothing can count that can also fail silently, gets a single
indeterminate indicator instead, and it belongs in the row where progress is
reported rather than in a content panel: see ``MainWindow.start_activity``.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from theme import qt as theme_qt
from utils.translation import _


class LoadingWidget(QWidget):
    """The line, and the bar when the wait can be counted."""

    #: How long a wait may run before it is worth mentioning. Below this the
    #: message would be on screen for less time than it takes to read.
    QUIET_MS = 400

    #: Emitted when the wait has run long enough to say so. The container
    #: listens and brings this page forward then, rather than immediately.
    became_visible = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_qt.pad(self.layout(), 4)
        theme_qt.gap(self.layout(), 2)

        # One line, centred, muted — the same treatment the empty state gets,
        # because both are statements about the panel rather than about a
        # measurement. Which of the two is on screen is the difference between
        # "not here yet" and "does not exist", and they are never both.
        self.loading_label = QLabel(_("LOADING"), self)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_qt.set_role(self.loading_label, "hint")

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        # The number is stated below rather than inside the bar, where nothing
        # is readable against both the track and the fill.
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setMaximumWidth(400)

        # Status label
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        theme_qt.set_role(self.status_label, "hint")

        # Add widgets to layout
        self.layout().addStretch()
        self.layout().addWidget(self.loading_label)
        self.layout().addWidget(self.progress_bar)
        self.layout().addWidget(self.status_label)
        self.layout().addStretch()

        self._quiet_timer = QTimer(self)
        self._quiet_timer.setSingleShot(True)
        self._quiet_timer.timeout.connect(self.became_visible)

    def arm(self):
        """A wait has started. Say nothing about it yet.

        ``became_visible`` follows ``QUIET_MS`` later if the wait is still
        running by then. A wait that ends first says nothing at all, which is
        the point: a cached folder of a dozen rolls comes back inside the quiet
        window, and a message that flashes up and disappears reads as something
        having gone wrong rather than as something having been fast.
        """
        self.reset()
        self._quiet_timer.start(self.QUIET_MS)

    def disarm(self):
        """The wait is over — whether or not anything was ever said about it."""
        self._quiet_timer.stop()

    def update_progress(self, value: int, status_text: str = ""):
        """Update the progress bar and status text."""
        self.progress_bar.setValue(value)
        self.status_label.setText(f"{value}% · {status_text}" if status_text else f"{value}%")

    def reset(self):
        """Reset the progress bar and status text."""
        self.progress_bar.setValue(0)
        self.status_label.setText("")
