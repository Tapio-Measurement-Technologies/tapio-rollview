from utils import preferences
import matplotlib.pyplot as plt
import settings
from utils import preferences, profile_stats
from models.Profile import Profile
from utils.zoom_pan import ZoomPan
from scipy.signal import welch
from utils.profile_stats import Stats, calc_mean_profile
from utils.excluded_regions import get_included_samples
import numpy as np
from gui.widgets.stats import StatsWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QLabel
from PySide6.QtCore import Qt
from utils.translation import _

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
import logging

logging.getLogger('matplotlib').setLevel(logging.WARNING)

STYLE_AXVLINE = {
    'color': 'gray',
    'linestyle': '--',
    'linewidth': 1.5,
    'alpha': 0.7,
    'zorder': 0
}


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


class ProfileWidget(QWidget):
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

        self._setup_axes()
        self._setup_zoom_pan()

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

        self.customize_toolbar()

    def _setup_axes(self):
        """Set up the subplot axes based on current preferences."""
        # Clear existing axes
        self.figure.clear()

        if preferences.show_spectrum:
            self.profile_ax = self.figure.add_subplot(211)
            self.spectrum_ax = self.figure.add_subplot(212)
        else:
            self.profile_ax = self.figure.add_subplot(111)
            self.spectrum_ax = None

    def _setup_zoom_pan(self):
        """Set up zoom and pan handlers for all axes in the figure."""
        zp = ZoomPan(self.figure)
        self.zoom = zp.zoom_factory(base_scale=1.5)
        self.pan = zp.pan_factory()

    def _draw_excluded_regions_visualization(self, mean_profile_values, mean_profile_distances_converted):
        """Draw excluded regions visualization on the plot."""

        data, excluded_ranges_idx = get_included_samples(mean_profile_values, preferences.excluded_regions)

        # Draw each excluded region
        for i, (start_idx, end_idx) in enumerate(excluded_ranges_idx):
            if start_idx < end_idx and start_idx < len(mean_profile_distances_converted) and end_idx <= len(mean_profile_distances_converted):
                # Shade the excluded region
                self.profile_ax.axvspan(
                    mean_profile_distances_converted[start_idx],
                    mean_profile_distances_converted[end_idx - 1] if end_idx < len(mean_profile_distances_converted) else mean_profile_distances_converted[-1],
                    alpha=0.2,
                    color='gray',
                    label=_("EXCLUDED_REGION") if i == 0 else '',  # Only label first region
                    zorder=-1
                )
                # Add dashed vertical lines at the edges
                self.profile_ax.axvline(
                    mean_profile_distances_converted[start_idx],
                    **STYLE_AXVLINE
                )
                self.profile_ax.axvline(
                    mean_profile_distances_converted[end_idx - 1] if end_idx < len(mean_profile_distances_converted) else mean_profile_distances_converted[-1],
                    **STYLE_AXVLINE
                )

    def customize_toolbar(self):
        actions = self.toolbar.actions()
        icons_to_keep = ['Home', 'Zoom', 'Pan', 'Customize', 'Save', '']
        for action in actions:
            if action.iconText() not in icons_to_keep:
                self.toolbar.removeAction(action)

    def _draw_stats_on_figure(self):
        """Draw statistics as text boxes on the figure, similar to stats widget.

        Returns:
            List of text objects that were added (for cleanup)
        """
        if not len(self.mean_profile):
            return []

        added_texts = []

        # Get stats values
        stats_data = [
            (profile_stats.stat_labels[self.stats.mean.name], self.stats.mean(self.mean_profile), self.stats.mean.unit),
            (profile_stats.stat_labels[self.stats.std.name], self.stats.std(self.mean_profile), self.stats.std.unit),
            (profile_stats.stat_labels[self.stats.cv.name], self.stats.cv(self.mean_profile), self.stats.cv.unit),
            (profile_stats.stat_labels[self.stats.min.name], self.stats.min(self.mean_profile), self.stats.min.unit),
            (profile_stats.stat_labels[self.stats.max.name], self.stats.max(self.mean_profile), self.stats.max.unit),
            (profile_stats.stat_labels[self.stats.pp.name], self.stats.pp(self.mean_profile), self.stats.pp.unit),
        ]

        # Check limits for highlighting
        limits = preferences.alert_limits
        limit_dict = {limit['name']: limit for limit in limits}
        stat_functions = [self.stats.mean, self.stats.std, self.stats.cv, self.stats.min, self.stats.max, self.stats.pp]

        # Position stats below title, evenly spaced across width
        num_stats = len(stats_data)
        # Calculate spacing to distribute evenly across width
        # Leave smaller margins on both sides
        left_margin = 0.1
        right_margin = 0.1
        usable_width = 1.0 - left_margin - right_margin
        spacing = usable_width / num_stats

        # Position at top of figure area (adjust based on tight_layout)
        # Using figure coordinates where 1.0 is top
        y_pos = 0.91

        for i, (label, value, unit) in enumerate(stats_data):
            stat_func = stat_functions[i]
            stat_name = getattr(stat_func, 'name', None)

            # Check if over limit
            over_limit = False
            if stat_name and stat_name in limit_dict:
                limit = limit_dict[stat_name]
                if limit['min'] is not None and value < limit['min']:
                    over_limit = True
                if limit['max'] is not None and value > limit['max']:
                    over_limit = True

            # Create text box with smaller font
            text = f"{label} [{unit}]\n{value:.2f}"

            # Background color (matplotlib format: (R, G, B, alpha))
            bgcolor = (1.0, 0.0, 0.0, 0.3) if over_limit else 'white'

            # With ha='right', position the right edge at the right side of allocated space
            # This centers the fixed-width box in its allocated space
            x_pos = left_margin + (i + 1) * spacing

            text_obj = self.figure.text(
                x_pos, y_pos,
                text,
                ha='right', va='top',
                fontsize=7,
                bbox=dict(boxstyle='square,pad=0.3', facecolor=bgcolor, edgecolor='lightgray', linewidth=0),
                transform=self.figure.transFigure,
            )
            added_texts.append(text_obj)

        return added_texts

    def clear(self):
        self.profile_ax.clear()
        self.profile_ax.figure.canvas.draw()  # Ensure the profile plot updates
        self.warning_label.clear()
        if preferences.show_spectrum and self.spectrum_ax is not None:
            self.spectrum_ax.clear()
            self.spectrum_ax.figure.canvas.draw()

    def update_plot(self, profiles: list[Profile], directory_name, selected=''):
        # Reconfigure axes layout
        self._setup_axes()

        # Update toolbar visibility
        self.toolbar.setVisible(preferences.show_plot_toolbar)

        self.clear()
        self.figure.suptitle(directory_name)

        # Filter empty profiles
        self.profiles = [
            profile for profile in profiles if profile.data is not None]
        self.directory_name = directory_name
        self.selected_file = selected

        # Get distance unit info
        unit_info = preferences.get_distance_unit_info()

        self.profile_ax.set_ylabel(f"{_("CHART_HARDNESS_LABEL")} [g]")
        self.profile_ax.set_xlabel(f"{_("CHART_DISTANCE_LABEL")} [{unit_info.unit}]")
        previous_distance = 0

        if len(self.profiles) == 0:
            self.profile_ax.text(0.5, 0.5, "No data available", ha="center", va="center",
                                 transform=self.profile_ax.transAxes, fontdict={'size': 16})
            self.canvas.draw()
            return

        for i, profile in enumerate(self.profiles):

            distances = np.array(profile.data.distances) + previous_distance
            # Convert distances to selected unit
            distances = distances * unit_info.conversion_factor
            hardnesses = profile.data.hardnesses

            linestyle = 'solid'
            if profile.hidden:
                linestyle = 'None'

            if preferences.continuous_mode and not profile.hidden:
                previous_distance = (distances[-1] / unit_info.conversion_factor) + settings.SAMPLE_INTERVAL_M
                if i > 0:
                    # Add marker between profiles at the first hardness value
                    self.profile_ax.plot(distances[0], hardnesses[0], marker='v',
                                       color='k', markersize=4, alpha=0.5, zorder=np.inf)

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
            # Convert mean profile distances to selected unit
            mean_profile_distances_converted = mean_profile_distances * unit_info.conversion_factor
            self.profile_ax.plot(mean_profile_distances_converted,
                                 mean_profile_values,
                                 label=_("CHART_MEAN_PROFILE_LABEL"),
                                 lw=settings.MEAN_PROFILE_LINE_WIDTH,
                                 color=settings.MEAN_PROFILE_LINE_COLOR)

            # Visualize excluded regions when enabled
            if preferences.excluded_regions_enabled:
                self._draw_excluded_regions_visualization(mean_profile_values, mean_profile_distances_converted)
        else:
            self.warning_label.set_text(
                _("CHART_WARNING_TEXT_TOO_SHORT_PROFILES"))

        if preferences.show_spectrum:
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

        if settings.SPECTRUM_WAVELENGTH_TICKS and preferences.show_spectrum:
            self.update_ticks_wavelength()
            self.spectrum_ax.callbacks.connect(
                'xlim_changed', self.update_ticks_wavelength)
            self.spectrum_ax.figure.canvas.mpl_connect(
                'resize_event', self.update_ticks_wavelength)

        self.figure.suptitle(directory_name)
        if hasattr(settings, 'GRID') and settings.GRID is not None:
            self.profile_ax.grid()
            if preferences.show_spectrum:
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

        self.profile_ax.legend(loc="upper right")
        self.figure.tight_layout()
        self.canvas.draw()

        # Push current view to toolbar's view stack for Home button (correctly reset modifications from custom ZoomPan)
        self.toolbar.push_current()

        self.stats_widget.update_data(self.mean_profile)

    def update_ticks_wavelength(self, *args):
        primary_ticks = self.spectrum_ax.get_xticks()
        wavelenght_ticks = [100 * (1 / i) if i != 0 else 0 for i in primary_ticks]
        self.spectrum_ax.set_xticks(primary_ticks) # Fixes matplotlib warning about fixed ticks
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
