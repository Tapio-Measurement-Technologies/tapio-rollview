import settings
import theme
from theme import icons
from theme import mpl as tapio_mpl
from theme import qt as theme_qt
from utils import preferences, profile_stats
from models.Profile import Profile
from utils.zoom_pan import ZoomPan
from scipy.signal import welch
from utils.profile_stats import Stats, calc_mean_profile, has_profile_samples
from utils.excluded_regions import get_included_samples, get_visual_excluded_ranges
from utils.highlighted_regions import (
    AbsoluteMeanOffsetHardnessHighlightRegion,
    RelativeMeanOffsetHardnessHighlightRegion,
    get_visual_distance_highlight_regions,
    get_visual_hardness_highlight_regions,
)
import numpy as np
from gui.widgets.stats import StatsWidget, format_stat_value
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QSizePolicy, QLabel
from PySide6.QtCore import QEvent, Qt, QThread, QTimer
from utils.translation import _

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from gui.widgets.PlotCanvas import PlotCanvas
import logging
import store

logging.getLogger('matplotlib').setLevel(logging.WARNING)

# Excluded-region boundaries. Grey and dashed: an excluded region is not an
# alarm, so it never borrows the limit colour.
STYLE_AXVLINE = {
    'linestyle': '--',
    'linewidth': 1.0,
    'alpha': 0.7,
    'zorder': 0
}

STYLE_HIGHLIGHT_MEAN_LINE = {
    'linestyle': (0, (5, 4)),
    'linewidth': tapio_mpl.TARGET_WIDTH,
    'alpha': 0.8,
    'zorder': -1,
}


def _highlight_edge_style(color):
    return {
        'color': color,
        'linestyle': '--',
        'linewidth': 0.9,
        'alpha': 0.55,
        'zorder': -1,
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
    """An inline banner: a condition that persists until it is resolved.

    Not a toast — a toast confirms that something happened. This says something
    is wrong with what is on screen, and stays until it is not.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        theme_qt.set_property(self, "banner", "warn")
        self.setHidden(True)

    def set_text(self, text):
        tokens = theme_qt.tokens()
        mark = icons.write_png(theme.STATUS_WARN, 13, tokens.color("warn"))
        self.setHidden(False)
        self.setText(f'<img src="{mark}" width="13" height="13">&nbsp;&nbsp;{text}')
        self.setAccessibleName(text)

    def clear(self):
        self.setHidden(True)
        self.setText("")


class PlotToolbar(NavigationToolbar):
    """The Matplotlib navigation bar, re-tinted when the theme changes.

    Matplotlib bakes each icon at construction: it reads the toolbar's palette
    and, only if the background is dark, masks the black glyph and refills it
    with the foreground colour. It never looks again. So a bar built in the
    light theme keeps black icons on the dark theme's near-black ground, and
    one built in dark keeps near-white icons on white — invisible either way.

    Qt delivers PaletteChange to every widget when the application palette is
    replaced, which is exactly what theme.apply() does, so the re-tint happens
    on its own rather than being something a caller has to remember.
    """

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)
        # What each action was drawn from. Matplotlib keeps this in a private
        # map keyed by callback name; reading it once here means a change to
        # its internals shows up as icons that stop updating, which the test
        # suite checks, rather than an exception in front of an operator.
        self._icon_files = {}
        actions = getattr(self, "_actions", {})
        for text, _tooltip, image_file, callback in self.toolitems:
            action = actions.get(callback)
            if text is None or not image_file or action is None:
                continue
            self._icon_files[action] = image_file + ".png"

    def retint(self):
        """Rebuild every icon against the palette the toolbar has now."""
        for action, filename in self._icon_files.items():
            action.setIcon(self._icon(filename))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self.retint()


class ProfileWidget(QWidget):
    """The profile tab: the verdict, then the chart.

    The tiles and the status pill answer "did it pass" before the operator reads
    a single axis, which is the whole point of putting them above the plot.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStatusTip(_("CHART_STATUS_TIP_TEXT"))

        self.layout = QVBoxLayout(self)
        theme_qt.pad(self.layout, 2, 2, 2, 1)
        theme_qt.gap(self.layout, 1)

        # None means "follow whatever theme the application is in". The plot
        # export sets a table here instead, so it can render light out of a dark
        # session without swapping the process-wide chart tokens that the GUI
        # thread reads while it draws.
        self.chart_tokens = None

        self.figure = Figure()
        self.warning_label = WarningLabel()
        self.empty_state_label = QLabel()
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme_qt.set_property(self.empty_state_label, "role", "emptyState")
        self.empty_state_label.setHidden(True)
        self.canvas = PlotCanvas(self.figure)
        self.stats = Stats()

        # None until the first _setup_axes() call decides an arrangement.
        self._axes_arrangement = None

        # The canvas reports when a resize has stopped. Laying out and
        # re-rendering on every event of a splitter drag is what left the window
        # unable to keep up with the pointer.
        self.canvas.on_resize_settled = self._relayout_figure

        # Matplotlib's own draw_idle() queues the repaint on a QTimer *it* owns,
        # which outlives this widget: destroy the tab with a draw pending and the
        # callback reaches a deleted C++ canvas. This timer is a child of the
        # widget, so it dies with it, and it collapses a burst of updates into
        # one render. It is None off the GUI thread — see _make_timer.
        self._draw_timer = self._make_timer(self._draw_now, interval=0)

        # The plot is the subject of this tab. Without a floor under the canvas
        # the tile grid squeezes it to a strip in which a profile cannot be
        # read; without headroom on the widget itself, the floor pushes the
        # chart toolbar out of the pane instead.
        self.setMinimumHeight(380)
        self.setMinimumWidth(400)
        self.canvas.setMinimumHeight(180)

        self._setup_axes()
        self._setup_zoom_pan()

        self.toolbar = PlotToolbar(self.canvas, self)
        self.toolbar.setVisible(preferences.show_plot_toolbar)
        self.mean_profile = []
        self.mean_profile_distances = []
        self.stats_widget = StatsWidget((self.mean_profile_distances, self.mean_profile))
        # The profile's limit lines are the minimum's lower and the maximum's
        # upper limit, so editing either from a tile has to redraw the chart.
        self.stats_widget.limits_changed.connect(self.replot)

        self.layout.addWidget(self.stats_widget)
        self.layout.addWidget(self.warning_label)
        self.layout.addWidget(self.empty_state_label)

        # The toolbar acts on the chart directly above it, so the two are one
        # object and sit flush. Everything else in the column keeps the row gap.
        plot_area = QVBoxLayout()
        theme_qt.pad(plot_area, 0)
        theme_qt.gap(plot_area, 0)
        plot_area.addWidget(self.canvas)
        plot_area.addWidget(self.toolbar)
        self.layout.addLayout(plot_area)

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.customize_toolbar()

    def _make_timer(self, slot, interval=None):
        """A single-shot timer owned by this widget, or None off the GUI thread."""
        application = QApplication.instance()
        if application is None or QThread.currentThread() is not application.thread():
            return None
        timer = QTimer(self)
        timer.setSingleShot(True)
        if interval is not None:
            timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    def replot(self):
        """Redraw what is already loaded, after something around it changed."""
        if getattr(self, "profiles", None):
            self.update_plot(self.profiles, self.directory_name)

    @property
    def tokens(self):
        """The chart tokens this widget draws with.

        The live table unless something has pinned one — which only the plot
        export does, and only for the figure it renders off the GUI thread.
        """
        return self.chart_tokens or tapio_mpl.current

    def _setup_axes(self, force=False):
        """Set up the subplot axes based on current preferences.

        Rebuilding the figure means tearing down and re-creating every axis,
        tick and spine, which is a large part of what made stepping through the
        folder list feel slow. The arrangement only depends on whether the
        spectrum is shown, so the axes are reused until that changes and
        emptied in place instead.
        """
        arrangement = bool(preferences.show_spectrum)
        if not force and arrangement == self._axes_arrangement and self.figure.axes:
            for ax in self.figure.axes:
                ax.clear()
            return

        # Clear existing axes
        self.figure.clear()
        self._axes_arrangement = arrangement

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

    def _get_excluded_region_plot_ranges(self, mean_profile_distances, conversion_factor):
        """Return excluded-region plot ranges in the current display unit."""
        visual_ranges = get_visual_excluded_ranges(
            preferences.excluded_regions,
            mode=preferences.excluded_regions_mode,
            distances=mean_profile_distances,
            absolute_scale=1 / conversion_factor,
        )
        return [
            (start * conversion_factor, end * conversion_factor)
            for start, end in visual_ranges
        ]

    def _get_distance_highlight_region_plot_ranges(self, mean_profile_distances, conversion_factor):
        visual_regions = get_visual_distance_highlight_regions(
            preferences.distance_highlight_regions,
            mean_profile_distances,
            absolute_scale=1 / conversion_factor,
        )
        return [
            (region.start * conversion_factor, region.end * conversion_factor, region.color)
            for region in visual_regions
        ]

    def _get_hardness_highlight_region_plot_ranges(self, mean_profile_distances, mean_profile_values):
        if len(mean_profile_values) == 0:
            return []

        mean_value = self.stats.mean((mean_profile_distances, mean_profile_values))
        plot_ranges = []
        for source_region in preferences.hardness_highlight_regions:
            visual_regions = get_visual_hardness_highlight_regions([source_region], mean_value)
            for region in visual_regions:
                plot_ranges.append(
                    (
                        region.start,
                        region.end,
                        region.color,
                        isinstance(source_region, (AbsoluteMeanOffsetHardnessHighlightRegion, RelativeMeanOffsetHardnessHighlightRegion)),
                        mean_value,
                    )
                )
        return plot_ranges

    def _draw_distance_highlight_region_edges(self, start_x, end_x, color):
        self.profile_ax.axvline(start_x, **_highlight_edge_style(color))
        if end_x != start_x:
            self.profile_ax.axvline(end_x, **_highlight_edge_style(color))

    def _draw_hardness_highlight_region_edges(self, start_y, end_y, color):
        self.profile_ax.axhline(start_y, **_highlight_edge_style(color))
        if end_y != start_y:
            self.profile_ax.axhline(end_y, **_highlight_edge_style(color))

    def _draw_hardness_highlight_mean_line(self, mean_value):
        self.profile_ax.axhline(
            mean_value,
            color=self.tokens.chart("target"),
            **STYLE_HIGHLIGHT_MEAN_LINE,
        )

    def _draw_distance_highlight_regions_visualization(self, mean_profile_distances, conversion_factor):
        for start_x, end_x, color in self._get_distance_highlight_region_plot_ranges(
            mean_profile_distances,
            conversion_factor,
        ):
            if start_x < end_x:
                self.profile_ax.axvspan(
                    start_x,
                    end_x,
                    alpha=0.2,
                    color=color,
                    zorder=-2,
                )
                self._draw_distance_highlight_region_edges(start_x, end_x, color)

    def _draw_hardness_highlight_regions_visualization(self, mean_profile_distances, mean_profile_values):
        mean_line_drawn = False
        for start_y, end_y, color, is_around_mean, mean_value in self._get_hardness_highlight_region_plot_ranges(
            mean_profile_distances,
            mean_profile_values,
        ):
            if start_y < end_y:
                self.profile_ax.axhspan(
                    start_y,
                    end_y,
                    alpha=0.15,
                    color=color,
                    zorder=-3,
                )
                self._draw_hardness_highlight_region_edges(start_y, end_y, color)
                if is_around_mean and not mean_line_drawn:
                    self._draw_hardness_highlight_mean_line(mean_value)
                    mean_line_drawn = True

    def _get_spectrum_plot_data(self, mean_profile_values):
        f, Pxx = welch(mean_profile_values,
                       fs=(1/settings.SAMPLE_INTERVAL_M),
                       window='hann',
                       nperseg=settings.NPERSEG,
                       noverlap=settings.NOVERLAP,
                       scaling='spectrum')
        mask = (
            (f >= settings.SPECTRUM_LOWER_LIMIT_1M) &
            (f <= settings.SPECTRUM_UPPER_LIMIT_1M)
        )
        return f[mask], np.sqrt(Pxx)[mask]

    def _draw_excluded_regions_visualization(self, mean_profile_distances, conversion_factor):
        """Draw excluded regions visualization on the plot.

        Excluded regions are drawn, never removed: an operator must be able to
        see what was left out of the statistics.
        """
        visual_ranges = self._get_excluded_region_plot_ranges(
            mean_profile_distances,
            conversion_factor,
        )
        edge = self.tokens.color("border-strong")

        # Draw each excluded region
        for i, (start_x, end_x) in enumerate(visual_ranges):
            if start_x < end_x:
                tapio_mpl.excluded(
                    self.profile_ax,
                    start_x,
                    end_x,
                    label=_("CHART_EXCLUDED_REGION_LEGEND") if i == 0 else None,
                    t=self.tokens,
                )

            self.profile_ax.axvline(start_x, color=edge, **STYLE_AXVLINE)
            if end_x != start_x:
                self.profile_ax.axvline(end_x, color=edge, **STYLE_AXVLINE)

    def customize_toolbar(self):
        actions = self.toolbar.actions()
        icons_to_keep = ['Home', 'Zoom', 'Pan', 'Customize', 'Save', '']
        for action in actions:
            if action.iconText() not in icons_to_keep:
                self.toolbar.removeAction(action)

    def _reset_toolbar_history(self):
        """Reset toolbar navigation history to the current plot state."""
        nav_stack = getattr(self.toolbar, "_nav_stack", None)
        if nav_stack is None:
            return

        nav_stack.clear()
        self.toolbar.push_current()

    def _sync_toolbar_layout_positions(self):
        """Keep toolbar Home/Back/Forward layout in sync after resize."""
        nav_stack = getattr(self.toolbar, "_nav_stack", None)
        if nav_stack is None or not getattr(nav_stack, "_elements", None):
            return

        current_positions = {
            ax: (ax.get_position(True).frozen(), ax.get_position().frozen())
            for ax in self.figure.axes
        }

        for nav_state in nav_stack._elements:
            if nav_state is None:
                continue
            for ax, (view, _) in list(nav_state.items()):
                if ax in current_positions:
                    nav_state[ax] = (view, current_positions[ax])

    def _draw_stats_on_figure(self):
        """Draw the heading and the stat tiles onto the figure, for export.

        The exported PNG is the whole verdict on its own — it goes into a mill
        report with no window around it — so it carries what the window carries:
        the roll name, then the tiles, then the chart. Same rules as on screen:
        eyebrow label, the number in mono, and only the failing tile in red.

        Returns:
            List of artists that were added (for cleanup). One of them restores
            the layout rather than removing an artist, so the on-screen figure is
            unchanged once the export has been taken.
        """
        if not len(self.mean_profile):
            return []

        added_texts = []
        t = self.tokens

        # Open a band across the top for the heading and the tiles, and put the
        # roll name there instead of on the axes, where it would land on them.
        added_texts.append(self._reserve_export_band())

        # Get stats values
        stats_data = [
            (profile_stats.stat_labels[self.stats.mean.name], self.stats.mean((self.mean_profile_distances, self.mean_profile)), self.stats.mean.unit),
            (profile_stats.stat_labels[self.stats.std.name], self.stats.std((self.mean_profile_distances, self.mean_profile)), self.stats.std.unit),
            (profile_stats.stat_labels[self.stats.cv.name], self.stats.cv((self.mean_profile_distances, self.mean_profile)), self.stats.cv.unit),
            (profile_stats.stat_labels[self.stats.min.name], self.stats.min((self.mean_profile_distances, self.mean_profile)), self.stats.min.unit),
            (profile_stats.stat_labels[self.stats.max.name], self.stats.max((self.mean_profile_distances, self.mean_profile)), self.stats.max.unit),
            (profile_stats.stat_labels[self.stats.pp.name], self.stats.pp((self.mean_profile_distances, self.mean_profile)), self.stats.pp.unit),
            (profile_stats.stat_labels[self.stats.slope.name], self.stats.slope((self.mean_profile_distances, self.mean_profile)), self.stats.slope.unit),
        ]

        # Check limits for highlighting
        limits = preferences.alert_limits
        limit_dict = {limit['name']: limit for limit in limits}
        stat_functions = [self.stats.mean, self.stats.std, self.stats.cv, self.stats.min, self.stats.max, self.stats.pp, self.stats.slope]

        # Position stats below title, evenly spaced across width
        num_stats = len(stats_data)
        # Calculate spacing to distribute evenly across width
        # Leave smaller margins on both sides
        left_margin = 0.1
        right_margin = 0.1
        usable_width = 1.0 - left_margin - right_margin
        spacing = usable_width / num_stats

        # Position at top of figure area, inside the band reserved above.
        y_pos = 0.86

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

            # With ha='right', position the right edge at the right side of allocated space
            # This centers the fixed-width box in its allocated space
            x_pos = left_margin + (i + 1) * spacing

            box = dict(
                boxstyle='round,pad=0.34,rounding_size=0.25',
                facecolor=t.color("bad-soft") if over_limit else t.color("surface"),
                edgecolor=t.color("bad-mark") if over_limit else t.color("border"),
                linewidth=0.8,
            )
            eyebrow = self.figure.text(
                x_pos, y_pos,
                f"{label} [{unit}]",
                ha='right', va='top',
                fontsize=6, family='monospace',
                color=t.color("ink-muted"),
                bbox=box,
                transform=self.figure.transFigure,
            )
            added_texts.append(eyebrow)

            value_text = self.figure.text(
                x_pos, y_pos - 0.055,
                format_stat_value(value),
                ha='right', va='top',
                fontsize=9, family='monospace', weight='medium',
                color=t.color("bad") if over_limit else t.color("ink"),
                transform=self.figure.transFigure,
            )
            added_texts.append(value_text)

        return added_texts

    def _reserve_export_band(self):
        """Make room above the axes for the export heading and tiles.

        Returns an object whose ``remove()`` puts the figure back, so it can
        travel with the text artists the exporter cleans up afterwards.
        """
        profile_widget = self

        class _Band:
            def __init__(self):
                # Titles are left-aligned system-wide (`axes.titlelocation`), and
                # get_title() reads the centre slot unless told otherwise.
                self.location = "left"
                self.title = profile_widget.profile_ax.get_title(loc=self.location)
                self.top = profile_widget.figure.subplotpars.top
                profile_widget.profile_ax.set_title("", loc=self.location)
                profile_widget.figure.subplots_adjust(top=0.72)
                t = profile_widget.tokens
                self.heading = profile_widget.figure.text(
                    0.1, 0.965, self.title,
                    ha="left", va="top",
                    fontsize=tapio_mpl.points(t.font_size("title-3")), weight="semibold",
                    color=t.color("ink"),
                    transform=profile_widget.figure.transFigure,
                )

            def remove(self):
                self.heading.remove()
                profile_widget.profile_ax.set_title(self.title, loc=self.location)
                profile_widget.figure.subplots_adjust(top=self.top)

        return _Band()

    def clear(self):
        """Empty the axes without repainting.

        This runs at the top of update_plot, which draws the finished figure
        anyway — rendering the blank axes first cost a full Agg pass (about half
        of update_plot's time) to show something nobody sees.
        """
        self.profile_ax.clear()
        self.warning_label.clear()
        if preferences.show_spectrum and self.spectrum_ax is not None:
            self.spectrum_ax.clear()

    def clear_plot_display(self):
        self.profiles = []
        self.mean_profile = []
        self.mean_profile_distances = []
        self.directory_name = None
        self.figure.clear()
        self._axes_arrangement = None
        tapio_mpl.restyle_figure(self.figure, self.tokens)
        self.canvas.sync_background()
        self.warning_label.clear()
        self.empty_state_label.clear()
        self.empty_state_label.setHidden(True)
        self.stats_widget.update_data(([], []))
        self.stats_widget.setVisible(False)
        self.canvas.setVisible(False)
        self.toolbar.setVisible(False)
        self.request_draw()

    def show_no_profile_files_message(self, directory_name):
        self.profiles = []
        self.mean_profile = []
        self.mean_profile_distances = []
        self.directory_name = directory_name
        self.figure.clear()
        self._axes_arrangement = None
        tapio_mpl.restyle_figure(self.figure, self.tokens)
        self.canvas.sync_background()
        self.warning_label.clear()
        self.stats_widget.update_data(([], []))
        self.stats_widget.setVisible(True)
        self.empty_state_label.setText(_("PROFILE_EMPTY_STATE_NO_PROFILES"))
        self.empty_state_label.setVisible(True)
        self.canvas.setVisible(False)
        self.toolbar.setVisible(False)
        self.request_draw()

    def update_plot(self, profiles: list[Profile], directory_name):
        self.stats_widget.setVisible(True)
        self.canvas.setVisible(True)
        self.empty_state_label.clear()
        self.empty_state_label.setHidden(True)

        # Filter empty profiles before drawing any axes. If there are no usable
        # profile files, the profile tab should show a UI message, not a plot.
        self.profiles = [
            profile for profile in profiles if has_profile_samples(profile)]
        if len(self.profiles) == 0:
            self.show_no_profile_files_message(directory_name)
            return

        # Reconfigure axes layout
        self._setup_axes()
        tapio_mpl.restyle_figure(self.figure, self.tokens)
        self.canvas.sync_background()

        # Update toolbar visibility
        self.toolbar.setVisible(preferences.show_plot_toolbar)

        self.warning_label.clear()

        self.directory_name = directory_name
        selected_profile_in_current_directory = store.selected_profile in [ p.name for p in self.profiles ]

        # Get distance unit info
        unit_info = preferences.get_distance_unit_info()

        previous_distance = 0

        # The individual profiles are one kind of thing — context behind the
        # mean — so they are one colour and one weight, however many of them a
        # folder holds. Only selection separates one from the rest.
        supporting_color, supporting_alpha = tapio_mpl.supporting_color(self.tokens)

        for i, profile in enumerate(self.profiles):
            if profile.hidden:
                continue

            distances = np.array(profile.data.distances) + previous_distance
            # Convert distances to selected unit
            distances = distances * unit_info.conversion_factor
            hardnesses = profile.data.hardnesses

            if preferences.continuous_mode:
                previous_distance = (distances[-1] / unit_info.conversion_factor) + settings.SAMPLE_INTERVAL_M
                if i > 0:
                    # Mark the seam between two stacked profiles.
                    self.profile_ax.plot(
                        distances[0], hardnesses[0], marker=7,
                        color=self.tokens.chart("tick"),
                        markersize=6, alpha=0.7, zorder=np.inf,
                    )

            selected = (
                selected_profile_in_current_directory
                and profile.name == store.selected_profile
            )
            tapio_mpl.supporting(
                self.profile_ax, distances, hardnesses,
                color=supporting_color,
                alpha=(supporting_alpha if not selected_profile_in_current_directory
                       else supporting_alpha * 0.6),
                selected=selected,
                selected_width=settings.SELECTED_PROFILE_LINE_WIDTH,
                t=self.tokens,
            )

        if preferences.recalculate_mean:
            self.profiles = [
                profile for profile in self.profiles if not profile.hidden]
        mean_profile_distances, mean_profile_values = calc_mean_profile(
            self.profiles)
        self.mean_profile_distances = mean_profile_distances
        self.mean_profile = mean_profile_values

        if len(mean_profile_values) > 0:
            # Convert mean profile distances to selected unit
            mean_profile_distances_converted = mean_profile_distances * unit_info.conversion_factor
            # The mean is the subject of this chart: series 1, at full weight
            # over the individual profiles behind it. The alert limits are not
            # drawn here — the stat tiles above carry them, with the number, the
            # limit and the verdict together.
            tapio_mpl.profile(
                self.profile_ax,
                mean_profile_distances_converted,
                mean_profile_values,
                label=_("CHART_MEAN_PROFILE_LABEL"),
                color=settings.MEAN_PROFILE_LINE_COLOR or tapio_mpl.series_color(0, self.tokens),
                width=settings.MEAN_PROFILE_LINE_WIDTH,
                t=self.tokens,
            )

            x_limits_before_distance_highlights = self.profile_ax.get_xlim()
            if preferences.distance_highlight_regions:
                self._draw_distance_highlight_regions_visualization(
                    mean_profile_distances,
                    unit_info.conversion_factor,
                )
                self.profile_ax.set_xlim(x_limits_before_distance_highlights)

            x_limits_before_hardness_highlights = self.profile_ax.get_xlim()
            if preferences.hardness_highlight_regions:
                self._draw_hardness_highlight_regions_visualization(
                    mean_profile_distances,
                    mean_profile_values,
                )
                self.profile_ax.set_xlim(x_limits_before_hardness_highlights)

            # Visualize excluded regions when enabled
            if preferences.excluded_regions_mode != settings.EXCLUDED_REGIONS_MODE_NONE:
                self._draw_excluded_regions_visualization(
                    mean_profile_distances,
                    unit_info.conversion_factor,
                )
        else:
            self.warning_label.set_text(
                _("CHART_WARNING_TEXT_TOO_SHORT_PROFILES"))

        if preferences.show_spectrum:
            spectrum_frequencies, spectrum_amplitudes = self._get_spectrum_plot_data(mean_profile_values)
            spectrum_color = tapio_mpl.series_color(0, self.tokens)
            self.spectrum_ax.plot(spectrum_frequencies, spectrum_amplitudes,
                                  color=spectrum_color)
            # Area fill under the curve gives the spectrum weight without
            # competing with anything sitting on top of it.
            self.spectrum_ax.fill_between(
                spectrum_frequencies, spectrum_amplitudes,
                color=spectrum_color, alpha=0.13, linewidth=0,
            )

            tapio_mpl.finish(
                self.spectrum_ax,
                xlabel=f"{_('CHART_FREQUENCY_LABEL')} [1/m]",
                ylabel=f"{_('CHART_AMPLITUDE_LABEL')} [{self.stats.mean.unit}]",
                t=self.tokens,
            )

        if settings.SPECTRUM_WAVELENGTH_TICKS and preferences.show_spectrum:
            self.update_ticks_wavelength()
            self.spectrum_ax.callbacks.connect(
                'xlim_changed', self.update_ticks_wavelength)
            self.spectrum_ax.figure.canvas.mpl_connect(
                'resize_event', self.update_ticks_wavelength)

        # The chart is titled with the object it shows, left-aligned like every
        # other title in the system.
        self.profile_ax.set_title(directory_name)
        tapio_mpl.finish(
            self.profile_ax,
            xlabel=f"{_('CHART_DISTANCE_LABEL')} [{unit_info.unit}]",
            ylabel=f"{_('CHART_HARDNESS_LABEL')} [{self.stats.mean.unit}]",
            t=self.tokens,
        )
        if not (hasattr(settings, 'GRID') and settings.GRID is not None):
            self.profile_ax.grid(False)
            if preferences.show_spectrum:
                self.spectrum_ax.grid(False)

        # Calculate max value from all plotted data
        max_plotted_value = 0
        if self.profiles:
            max_plotted_value = max(max(profile.data.hardnesses)
                                    for profile in self.profiles if profile.data is not None)
        if len(mean_profile_values) > 0:
            max_plotted_value = max(
                max_plotted_value, max(mean_profile_values))

        # Use per-user Y-limit overrides if provided, otherwise use selected default scaling mode.
        y_axis_scaling = getattr(preferences, "default_y_axis_scaling", settings.Y_AXIS_SCALING_DEFAULT)

        low = preferences.y_lim_low_override
        if low is None:
            if y_axis_scaling == settings.Y_AXIS_SCALING_FIT_TO_DATA:
                low = None
            else:
                low = settings.Y_LIM_LOW(0) if hasattr(
                    settings, 'Y_LIM_LOW') and settings.Y_LIM_LOW is not None else None

        high = preferences.y_lim_high_override
        if high is None:
            if y_axis_scaling == settings.Y_AXIS_SCALING_FIT_TO_DATA:
                high = None
            else:
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

        tapio_mpl.fit(self.figure)
        self.request_draw()

        self._reset_toolbar_history()

        self.stats_widget.update_data((self.mean_profile_distances, self.mean_profile))

    def update_ticks_wavelength(self, *args):
        primary_ticks = self.spectrum_ax.get_xticks()
        wavelenght_ticks = [100 * (1 / i) if i != 0 else 0 for i in primary_ticks]
        self.spectrum_ax.set_xticks(primary_ticks) # Fixes matplotlib warning about fixed ticks
        self.spectrum_ax.set_xticklabels(
            [f"{tick:.2f}" for tick in wavelenght_ticks], family="monospace")
        self.spectrum_ax.set_xlabel(f"{_("CHART_WAVELENGTH_LABEL")} [cm]")

    def clear_canvas(self):
        self.ax.clear()
        self.request_draw()

    def set_toolbar_visible(self, visible):
        self.toolbar.setVisible(visible)

    def request_draw(self):
        """Repaint the canvas once, after the current batch of work.

        Several updates in one go — a folder change that reloads profiles, then
        restores hidden state, then re-plots — collapse into a single render.
        """
        if self._draw_timer is None:
            self._draw_now()
            return
        self._draw_timer.start()

    def _draw_now(self):
        self.canvas.draw()

    def _relayout_figure(self):
        tapio_mpl.fit(self.figure)
        self._sync_toolbar_layout_positions()
        self.request_draw()
