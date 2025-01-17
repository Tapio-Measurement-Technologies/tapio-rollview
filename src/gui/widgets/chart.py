from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
import logging

logging.getLogger('matplotlib').setLevel(logging.WARNING)
from gui.widgets.stats import StatsWidget
import numpy as np
from utils.profile_stats import Stats, calc_mean_profile
from scipy.signal import welch
from utils.zoom_pan import ZoomPan
from models.Profile import Profile
from utils import preferences
import settings

from io import BytesIO
import matplotlib.pyplot as plt


class Chart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Existing initialization code
        self.layout = QVBoxLayout(self)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.stats = Stats()

        if settings.SHOW_SPECTRUM:
            self.profile_ax = self.figure.add_subplot(211)
            self.spectrum_ax = self.figure.add_subplot(212)
        else:
            self.profile_ax = self.figure.add_subplot(111)

        zp = ZoomPan()
        self.zoom = zp.zoom_factory(self.profile_ax, 1.5)
        self.pan = zp.pan_factory(self.profile_ax)

        self.toolbar = NavigationToolbar(self.canvas, self)
        self.mean_profile = []
        self.stats_widget = StatsWidget(self.mean_profile)

        self.layout.addWidget(self.stats_widget)
        self.layout.addWidget(self.canvas)
        self.layout.addWidget(self.toolbar)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.initial_xlim = None
        self.initial_ylim = None

        self.customize_toolbar()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events for the widget."""
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C:
            # Copy plot to clipboard when Ctrl+C is pressed
            if hasattr(self, 'figure') and self.figure:
                self.copyPlotToClipboard()
            else:
                print("Warning: No plot available to copy.")
        else:
            super().keyPressEvent(event)

    def copyPlotToClipboard(self):
        """Copies the current plot to the clipboard."""
        try:
            buffer = BytesIO()
            self.figure.savefig(buffer, format='png', dpi=300)
            buffer.seek(0)

            # Convert buffer to QImage
            image = QImage()
            image.loadFromData(buffer.read(), format='PNG')
            buffer.close()

            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setImage(image)
            print("Plot copied to clipboard.")
        except Exception as e:
            print(f"Error copying plot to clipboard: {e}")




    def customize_toolbar(self):
        actions = self.toolbar.actions()
        icons_to_keep = ['Home', 'Zoom', 'Pan', 'Save']
        for action in actions:
            if action.iconText() not in icons_to_keep:
                self.toolbar.removeAction(action)

        # Set custom Home button behavior
        for action in actions:
            if action.iconText() == 'Home':
                action.triggered.connect(self.reset_view)

    def reset_view(self):
        """Reset the view to the initial state."""
        if self.initial_xlim and self.initial_ylim:
            self.profile_ax.set_xlim(self.initial_xlim)
            self.profile_ax.set_ylim(self.initial_ylim)
            self.profile_ax.figure.canvas.draw()

    def clear(self):
        self.profile_ax.clear()
        self.profile_ax.figure.canvas.draw()  # Ensure the profile plot updates
        if settings.SHOW_SPECTRUM:
            self.spectrum_ax.clear()
            self.spectrum_ax.figure.canvas.draw()

    def update_plot(self, profiles: list[Profile], directory_name, selected='', show_stats_in_title=False):
        self.clear()
        self.figure.suptitle(directory_name)
        self.figure.canvas.draw()

        # Filter empty profiles
        self.profiles = [profile for profile in profiles if profile.data is not None]
        self.directory_name = directory_name
        self.selected_file = selected
        self.profile_ax.set_ylabel(settings.UNIT)
        self.profile_ax.set_xlabel("Distance [m]")
        previous_distance = 0
        for profile in self.profiles:

            distances = np.array(profile.data.distances) + previous_distance
            hardnesses = profile.data.hardnesses
            if settings.CONTINUOUS_MODE:
                previous_distance = distances[-1] + (1 / settings.SAMPLE_INTERVAL)

            linestyle = 'solid'
            if profile.hidden:
                linestyle = 'None'

            if selected:  # Highlight selected profile
                if profile.name == selected:

                    self.profile_ax.plot(distances,
                                         hardnesses,
                                         alpha=0.6,
                                         lw=settings.SELECTED_PROFILE_LINE_WIDTH,
                                         linestyle=linestyle,
                                         zorder=np.inf)
                else:
                    self.profile_ax.plot(distances, hardnesses, alpha=0.2, linestyle=linestyle)
            else:
                self.profile_ax.plot(distances, hardnesses, alpha=0.5, linestyle=linestyle)

        if preferences.recalculate_mean:
            self.profiles = [ profile for profile in self.profiles if not profile.hidden ]
        mean_profile_distances, mean_profile_values = calc_mean_profile(self.profiles)
        self.mean_profile = mean_profile_values

        self.profile_ax.plot(mean_profile_distances,
                             mean_profile_values,
                             label="Mean profile",
                             lw=settings.MEAN_PROFILE_LINE_WIDTH,
                             color=settings.MEAN_PROFILE_LINE_COLOR)

        self.initial_xlim = self.profile_ax.get_xlim()
        self.initial_ylim = self.profile_ax.get_ylim()

        if settings.SHOW_SPECTRUM:
            f, Pxx = welch(mean_profile_values,
                           fs=settings.SAMPLE_INTERVAL,
                           window='hann',
                           nperseg=settings.NPERSEG,
                           noverlap=settings.NOVERLAP,
                           scaling='spectrum')
            self.spectrum_ax.plot(f[settings.SPECTRUM_LOWER_LIMIT:settings.SPECTRUM_UPPER_LIMIT],
                                  np.sqrt(Pxx)[settings.SPECTRUM_LOWER_LIMIT:settings.SPECTRUM_UPPER_LIMIT])

            self.spectrum_ax.set_ylabel("Amplitude [g]")
            self.spectrum_ax.set_xlabel("Frequency [1/m]")

        if settings.SPECTRUM_WAVELENGTH_TICKS and settings.SHOW_SPECTRUM:
            self.update_ticks_wavelength()
            self.spectrum_ax.callbacks.connect('xlim_changed', self.update_ticks_wavelength)
            self.spectrum_ax.figure.canvas.mpl_connect('resize_event', self.update_ticks_wavelength)

        self.figure.suptitle(directory_name)
        if hasattr(settings, 'GRID') and settings.GRID is not None:
            self.profile_ax.grid()
            if settings.SHOW_SPECTRUM:
                self.spectrum_ax.grid()

        if hasattr(settings, 'Y_LIM_LOW') and settings.Y_LIM_LOW is not None:
            self.profile_ax.set_ylim(bottom=settings.Y_LIM_LOW(mean_profile_values))

        if hasattr(settings, 'Y_LIM_HIGH') and settings.Y_LIM_HIGH is not None:
            self.profile_ax.set_ylim(top=settings.Y_LIM_HIGH(mean_profile_values))

        if show_stats_in_title and len(self.mean_profile):
            title = (
                f"{self.stats.mean.label}: {self.stats.mean(self.mean_profile):.2f} {self.stats.mean.unit}    "
                f"{self.stats.min.label }: { self.stats.min(self.mean_profile):.2f} {self.stats.min.unit }    "
                f"{self.stats.max.label }: { self.stats.max(self.mean_profile):.2f} {self.stats.max.unit }\n"
                f"{self.stats.std.label }: { self.stats.std(self.mean_profile):.2f} {self.stats.std.unit }    "
                f"{self.stats.cv.label  }: {  self.stats.cv(self.mean_profile):.2f} {self.stats.cv.unit  }    "
                f"{self.stats.pp.label  }: {  self.stats.pp(self.mean_profile):.2f} {self.stats.pp.unit  }"
            )
            self.profile_ax.set_title(title)

        self.profile_ax.legend(loc="upper right")
        self.figure.tight_layout()
        self.canvas.draw()
        self.stats_widget.update_data(self.mean_profile)

    def update_ticks_wavelength(self, *args):
        primary_ticks = self.spectrum_ax.get_xticks()
        wavelenght_ticks = [100 * (1 / i) for i in primary_ticks]
        self.spectrum_ax.set_xticklabels([f"{tick:.2f}" for tick in wavelenght_ticks])
        self.spectrum_ax.set_xlabel("Wavelength [cm]")

    def clear_canvas(self):
        self.ax.clear()
        self.canvas.draw()

    def resizeEvent(self, event):
        """Handle the window resize event to update chart dimensions."""
        super().resizeEvent(event)
        self.figure.tight_layout()
        self.canvas.draw()
