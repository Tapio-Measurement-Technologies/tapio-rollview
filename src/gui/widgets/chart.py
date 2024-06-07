from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
import logging

logging.getLogger('matplotlib').setLevel(logging.WARNING)
from gui.widgets.stats import StatsWidget
import numpy as np
from utils.profile_stats import calc_mean_profile
from scipy.signal import welch
import settings


class Chart(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)

        if settings.SHOW_SPECTRUM:
            self.profile_ax = self.figure.add_subplot(211)
            self.spectrum_ax = self.figure.add_subplot(212)
        else:
            self.profile_ax = self.figure.add_subplot(111)

        self.toolbar = NavigationToolbar(self.canvas, self)
        self.mean_profile = []
        self.stats = StatsWidget(self.mean_profile)

        self.layout.addWidget(self.stats)
        self.layout.addWidget(self.canvas)
        self.layout.addWidget(self.toolbar)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.customize_toolbar()

    def customize_toolbar(self):
        actions = self.toolbar.actions()
        icons_to_keep = ['Home', 'Zoom', 'Pan', 'Save']
        for action in actions:
            if action.iconText() not in icons_to_keep:
                self.toolbar.removeAction(action)

    def clear(self):
        self.profile_ax.clear()
        if settings.SHOW_SPECTRUM:
            self.spectrum_ax.clear()

    def update_plot(self, profiles, directory_name, selected=''):
        self.clear()
        self.profiles = profiles
        self.directory_name = directory_name
        self.selected_file = selected
        self.profile_ax.set_ylabel(settings.UNIT)
        self.profile_ax.set_xlabel("Distance [m]")
        previous_distance = 0
        for profile in profiles:

            distances = np.array(profile['data'][0] / settings.SAMPLE_INTERVAL) + previous_distance
            if settings.CONTINUOUS_MODE:
                previous_distance = distances[-1] + (1 / settings.SAMPLE_INTERVAL)

            if selected:  # Highlight selected profile
                if profile['name'] == selected:

                    self.profile_ax.plot(distances,
                                         profile['data'][1],
                                         alpha=0.6,
                                         lw=settings.SELECTED_PROFILE_LINE_WIDTH,
                                         zorder=np.inf)
                else:
                    self.profile_ax.plot(distances, profile['data'][1], alpha=0.2)
            else:
                self.profile_ax.plot(distances, profile['data'][1], alpha=0.5)

        mean_profile_distances, mean_profile_values = calc_mean_profile(profiles)
        self.mean_profile = mean_profile_values
        print(mean_profile_values)

        self.profile_ax.plot(mean_profile_distances,
                             mean_profile_values,
                             label="Mean profile",
                             lw=settings.MEAN_PROFILE_LINE_WIDTH,
                             color=settings.MEAN_PROFILE_LINE_COLOR)

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

        self.profile_ax.legend(loc="upper right")
        self.figure.tight_layout()
        self.canvas.draw()
        self.stats.update_data(self.mean_profile)

    def update_ticks_wavelength(self, *args):
        primary_ticks = self.spectrum_ax.get_xticks()
        wavelenght_ticks = [100 * (1 / i) for i in primary_ticks]
        self.spectrum_ax.set_xticklabels([f"{tick:.2f}" for tick in wavelenght_ticks])
        self.spectrum_ax.set_xlabel("Wavelength [cm]")

    def clear_canvas(self):
        self.ax.clear()
        self.canvas.draw()
