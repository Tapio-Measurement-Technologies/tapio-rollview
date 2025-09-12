from utils import preferences
import matplotlib.pyplot as plt
from io import BytesIO
import settings
from utils import preferences, profile_stats
from models.Profile import Profile
from utils.zoom_pan import ZoomPan
from scipy.signal import welch
from utils.profile_stats import Stats, calc_mean_profile
import numpy as np
from gui.widgets.stats import StatsWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QLabel

from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from utils.translation import _

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
import logging

logging.getLogger('matplotlib').setLevel(logging.WARNING)


# Add support for Japanese characters
if preferences.locale == 'ja':
    import matplotlib
    import matplotlib.font_manager as font_manager
    font_path = settings.JP_FONT_PATH
    font_manager.fontManager.addfont(font_path)
    prop = font_manager.FontProperties(fname=font_path)
    matplotlib.rcParams['font.family'] = prop.get_name()


class WarningLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            background-color: lightgoldenrodyellow;
            border-radius: 4px;
            border: 2px;
        """)

    def set_text(self, text):
        self.setHidden(False)
        self.setText(f"⚠ {text}")

    def clear(self):
        self.setHidden(True)
        self.setText("")


class Chart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStatusTip(_("CHART_STATUS_TIP_TEXT"))

        # Existing initialization code
        self.layout = QVBoxLayout(self)
        self.figure = Figure()
        self.warning_label = WarningLabel()
        self.canvas = FigureCanvas(self.figure)
        self.stats = Stats()

        self.setMinimumHeight(400)
        self.setMinimumWidth(400)

        if settings.SHOW_SPECTRUM:
            self.profile_ax = self.figure.add_subplot(211)
            self.spectrum_ax = self.figure.add_subplot(212)
        else:
            self.profile_ax = self.figure.add_subplot(111)

        zp = ZoomPan()
        self.zoom = zp.zoom_factory(self.profile_ax, 1.5)
        self.pan = zp.pan_factory(self.profile_ax)

        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setVisible(preferences.show_plot_toolbar)
        self.mean_profile = []
        self.stats_widget = StatsWidget(self.mean_profile)

        self.layout.addWidget(self.stats_widget)
        self.layout.addWidget(self.warning_label)
        self.layout.addWidget(self.canvas)
        self.layout.addWidget(self.toolbar)

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.initial_xlim = None
        self.initial_ylim = None

        self.customize_toolbar()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events for the widget."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
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
        icons_to_keep = ['Home', 'Zoom', 'Pan', 'Customize', 'Save', '']
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
        self.warning_label.clear()
        if settings.SHOW_SPECTRUM:
            self.spectrum_ax.clear()
            self.spectrum_ax.figure.canvas.draw()

    def update_plot(self, profiles: list[Profile], directory_name, selected='', show_stats_in_title=False):
        self.clear()
        self.figure.suptitle(directory_name)

        # Filter empty profiles
        self.profiles = [
            profile for profile in profiles if profile.data is not None]
        self.directory_name = directory_name
        self.selected_file = selected
        self.profile_ax.set_ylabel(f"{_("CHART_HARDNESS_LABEL")} [g]")
        self.profile_ax.set_xlabel(f"{_("CHART_DISTANCE_LABEL")} [m]")
        previous_distance = 0

        if len(self.profiles) == 0:
            self.profile_ax.text(0.5, 0.5, "No data available", ha="center", va="center",
                                 transform=self.profile_ax.transAxes, fontdict={'size': 16})
            self.canvas.draw()
            return

        for profile in self.profiles:

            distances = np.array(profile.data.distances) + previous_distance
            hardnesses = profile.data.hardnesses

            linestyle = 'solid'
            if profile.hidden:
                linestyle = 'None'

            if settings.CONTINUOUS_MODE and not profile.hidden:
                previous_distance = distances[-1] + settings.SAMPLE_INTERVAL_M

            if selected:  # Highlight selected profile
                if profile.name == selected:

                    self.profile_ax.plot(distances,
                                         hardnesses,
                                         alpha=0.6,
                                         lw=settings.SELECTED_PROFILE_LINE_WIDTH,
                                         linestyle=linestyle,
                                         zorder=np.inf)
                else:
                    self.profile_ax.plot(
                        distances, hardnesses, alpha=0.2, linestyle=linestyle)
            else:
                self.profile_ax.plot(distances, hardnesses,
                                     alpha=0.3, linestyle=linestyle)

        if preferences.recalculate_mean:
            self.profiles = [
                profile for profile in self.profiles if not profile.hidden]
        mean_profile_distances, mean_profile_values = calc_mean_profile(
            self.profiles)
        self.mean_profile = mean_profile_values

        if len(mean_profile_values) > 0:
            self.profile_ax.plot(mean_profile_distances,
                                 mean_profile_values,
                                 label=_("CHART_MEAN_PROFILE_LABEL"),
                                 lw=settings.MEAN_PROFILE_LINE_WIDTH,
                                 color=settings.MEAN_PROFILE_LINE_COLOR)
        else:
            self.warning_label.set_text(
                _("CHART_WARNING_TEXT_TOO_SHORT_PROFILES"))

        self.initial_xlim = self.profile_ax.get_xlim()
        self.initial_ylim = self.profile_ax.get_ylim()

        if settings.SHOW_SPECTRUM:
            f, Pxx = welch(mean_profile_values,
                           fs=(1/settings.SAMPLE_INTERVAL_M),
                           window='hann',
                           nperseg=settings.NPERSEG,
                           noverlap=settings.NOVERLAP,
                           scaling='spectrum')
            self.spectrum_ax.plot(f[settings.SPECTRUM_LOWER_LIMIT:settings.SPECTRUM_UPPER_LIMIT],
                                  np.sqrt(Pxx)[settings.SPECTRUM_LOWER_LIMIT:settings.SPECTRUM_UPPER_LIMIT])

            self.spectrum_ax.set_ylabel(f"{_("CHART_AMPLITUDE_LABEL")} [g]")
            self.spectrum_ax.set_xlabel(f"{_("CHART_FREQUENCY_LABEL")} [1/m]")

        if settings.SPECTRUM_WAVELENGTH_TICKS and settings.SHOW_SPECTRUM:
            self.update_ticks_wavelength()
            self.spectrum_ax.callbacks.connect(
                'xlim_changed', self.update_ticks_wavelength)
            self.spectrum_ax.figure.canvas.mpl_connect(
                'resize_event', self.update_ticks_wavelength)

        self.figure.suptitle(directory_name)
        if hasattr(settings, 'GRID') and settings.GRID is not None:
            self.profile_ax.grid()
            if settings.SHOW_SPECTRUM:
                self.spectrum_ax.grid()

        # Calculate max value from all plotted data
        max_plotted_value = 0
        if self.profiles:
            max_plotted_value = max(max(profile.data.hardnesses)
                                    for profile in self.profiles if profile.data is not None)
        if len(mean_profile_values) > 0:
            max_plotted_value = max(
                max_plotted_value, max(mean_profile_values))

        #  Only set axis limits if values are finite
        low = settings.Y_LIM_LOW(0) if hasattr(
            settings, 'Y_LIM_LOW') and settings.Y_LIM_LOW is not None else None
        high = settings.Y_LIM_HIGH(max_plotted_value) if hasattr(
            settings, 'Y_LIM_HIGH') and settings.Y_LIM_HIGH is not None else None

        if low is not None and np.isfinite(low):
            self.profile_ax.set_ylim(bottom=low)
        elif low is not None and not np.isfinite(low):
            self.warning_label.set_text("Y_LIM_LOW is not a finite value.")

        if high is not None and np.isfinite(high):
            self.profile_ax.set_ylim(top=high)
        elif high is not None and not np.isfinite(high):
            self.warning_label.set_text("Y_LIM_HIGH is not a finite value.")

        if show_stats_in_title and len(self.mean_profile):
            title = (
                f"{profile_stats.stat_labels[self.stats.mean.name]}: {self.stats.mean(self.mean_profile):.2f} {self.stats.mean.unit}    "
                f"{profile_stats.stat_labels[self.stats.min.name]}: {self.stats.min(self.mean_profile):.2f} {self.stats.min.unit}    "
                f"{profile_stats.stat_labels[self.stats.max.name]}: {self.stats.max(self.mean_profile):.2f} {self.stats.max.unit}\n"
                f"{profile_stats.stat_labels[self.stats.std.name]}: {self.stats.std(self.mean_profile):.2f} {self.stats.std.unit}    "
                f"{profile_stats.stat_labels[self.stats.cv.name]}: {self.stats.cv(self.mean_profile):.2f} {self.stats.cv.unit}    "
                f"{profile_stats.stat_labels[self.stats.pp.name]}: {self.stats.pp(self.mean_profile):.2f} {self.stats.pp.unit}"
            )
            self.profile_ax.set_title(title)

        self.profile_ax.legend(loc="upper right")
        self.figure.tight_layout()
        self.canvas.draw()
        self.stats_widget.update_data(self.mean_profile)

    def update_ticks_wavelength(self, *args):
        primary_ticks = self.spectrum_ax.get_xticks()
        wavelenght_ticks = [100 * (1 / i) for i in primary_ticks]
        self.spectrum_ax.set_xticklabels(
            [f"{tick:.2f}" for tick in wavelenght_ticks])
        self.spectrum_ax.set_xlabel(f"{_("CHART_WAVELENGTH_LABEL")} [cm]")

    def clear_canvas(self):
        self.ax.clear()
        self.canvas.draw()

    def set_toolbar_visible(self, visible):
        self.toolbar.setVisible(visible)

    def resizeEvent(self, event):
        """Handle the window resize event to update chart dimensions."""
        super().resizeEvent(event)
        self.figure.tight_layout()
        self.canvas.draw()
