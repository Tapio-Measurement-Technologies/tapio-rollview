from PySide6.QtWidgets import (
    QWidget,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QPushButton,
    QLabel,
    QSizePolicy,
)
from PySide6.QtCore import Slot, Signal, Qt
import store
import os
from typing import List, Dict, Any
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from gui.widgets.PlotCanvas import PlotCanvas
from datetime import datetime, timedelta
from utils.translation import _
from utils import preferences
from utils import profile_stats
from workers.statistics_processor import StatisticsProcessor
from gui.widgets.LoadingWidget import LoadingWidget
from theme import mpl as tapio_mpl
from theme import tokens as T
from theme import qt as theme_qt
from theme.widgets import SectionLabel

stat_label_map = profile_stats.analysis_stat_label_map

class StatSelectionDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(list(stat_label_map.keys()))

class FilterDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems([_("FILTER_LAST_7_DAYS"), _("FILTER_LAST_30_DAYS"), _("FILTER_SHOW_ALL_ROLLS")])
        self.setCurrentText(_("FILTER_LAST_7_DAYS"))

class StatisticsAnalysisChart(QWidget):
    point_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent  # Store direct reference
        self.figure = Figure()
        self.canvas = PlotCanvas(self.figure, self._relayout_figure)
        self.empty_state_label = QLabel()
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        theme_qt.set_property(self.empty_state_label, "role", "emptyState")
        self.empty_state_label.setHidden(True)
        self.ax = self.figure.add_subplot(111)
        self.stat_data = []
        self.bars = []
        self.highlighted_point = None
        self.current_filter = None  # Track current filter for display

        layout = QVBoxLayout()
        theme_qt.pad(layout, 0)
        theme_qt.gap(layout, 0)
        layout.addWidget(self.empty_state_label)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.canvas.mpl_connect("pick_event", self.on_pick)
        self.canvas.mpl_connect('motion_notify_event', self.on_hover)

    def _relayout_figure(self):
        """Re-fit and redraw once the canvas has stopped changing size."""
        tapio_mpl.fit(self.figure)
        self.canvas.draw()

    def highlight_point(self, label: str):
        self.highlighted_point = label
        self.plot(self.stat_data)

    def plot(self, stat_data: List[Dict[str, Any]]):
        self.stat_data = stat_data
        self.ax.clear()
        self.bars = []
        t = tapio_mpl.current
        tapio_mpl.restyle_figure(self.figure, t)
        self.canvas.sync_background()
        self.annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(0, 10), textcoords="offset points",
            fontsize=tapio_mpl.points(t.font_size("body-sm")), color=t.color("ink"),
            bbox=dict(boxstyle="round,pad=0.4", facecolor=t.color("raised"),
                      edgecolor=t.color("border-strong"), linewidth=1.0),
            zorder=20,
        )
        self.annot.set_visible(False)

        if not stat_data:
            self.empty_state_label.setText(_("NO_DATA_AVAILABLE"))
            self.empty_state_label.setVisible(True)
            self.canvas.setVisible(False)
            self.canvas.draw()
            return

        self.empty_state_label.clear()
        self.empty_state_label.setHidden(True)
        self.canvas.setVisible(True)

        # Use enumerated indices for x-axis instead of timestamps
        x_indices = list(range(len(stat_data)))
        y = [p['y'] for p in stat_data]

        limit_low = limit_high = None
        # Add alert limit ranges as shaded areas if available (draw behind bars)
        if hasattr(self.parent_widget, 'selected_stat'):
            current_stat = self.parent_widget.selected_stat
            alert_name = profile_stats.analysis_to_alert_name.get(current_stat)
            matching_limit = next(
                (limit for limit in preferences.alert_limits if limit['name'] == alert_name),
                None,
            )

            if matching_limit and (matching_limit['min'] is not None or matching_limit['max'] is not None):
                # The wash marks the region *beyond* the limit, not the region
                # inside it: a violation should be a shape the eye finds before
                # it reads the axis, and the in-spec case should look calm.
                limit_low = matching_limit['min']
                limit_high = matching_limit['max']

        base_color = t.recency[0]
        bar_width = 0.7
        self.bars = self.ax.bar(x_indices, y, width=bar_width, alpha=1,
                                color=base_color, picker=5, zorder=2)

        # A bar that crossed its limit is status, and status outranks identity.
        for bar, value in zip(self.bars, y):
            if ((limit_low is not None and value < limit_low)
                    or (limit_high is not None and value > limit_high)):
                bar.set_facecolor(t.chart("limit"))

        # Selection is a change of fill, on every bar, whatever it is filled
        # with. It used to be an outline on a failing bar and a change of hue on
        # a passing one: set_color() writes the edge as well as the face, so on
        # a passing bar it overwrote the outline that had just been set, and the
        # two states ended up looking nothing like each other.
        #
        # The selected bar keeps its hue and steps toward the ink, so a failing
        # bar still reads as failing and a passing one as passing. Toward the
        # ink rather than lighter or darker outright, because that is the
        # direction that separates from the ground in both themes: near-black
        # over a light panel, near-white over a dark one.
        if self.highlighted_point:
            for i, p in enumerate(stat_data):
                if p['label'] == self.highlighted_point:
                    fill = to_hex(self.bars[i].get_facecolor())
                    self.bars[i].set_facecolor(T.mix(t.color("ink"), fill, 0.35))
                    self.bars[i].set_alpha(1.0)
                    break

        # Limit lines go on last, so they can reach the final axes extent rather
        # than whatever it was before the bars were drawn.
        #
        # No wash here, unlike the profile chart. There it earns its place: a
        # curve carries no per-point status, so the shaded region is what the
        # eye finds first. A bar already says whether it passed by its own
        # colour, which leaves the wash restating it — and restating it over
        # whatever share of the axis falls outside the limits, which for a
        # statistic that ranges far past its limit is most of the plot. Seventy
        # per cent of the panel tinted red buys nothing and costs the contrast
        # every other mark needs.
        # The line is ink, not the limit red, because the bars it has to be read
        # against are that red already — two marks in the same hex are one mark,
        # and the line disappeared wherever it crossed a failing bar. A limit is
        # a reference rather than data, so it takes the one colour guaranteed to
        # separate from every fill on the panel in both themes.
        # The line keeps the limit red and goes *behind* the bars. Colour was
        # the wrong lever: on top it either fought the red bars it crossed or,
        # in a colour loud enough to win, out-shouted the data it was there to
        # judge. A limit belongs on the ground the data stands on — clearly
        # visible across the background, occluded by whatever crosses it, which
        # is also the moment the bar's own colour has already said so.
        limit_line = tapio_mpl.limit_line_color(t)
        # The value rides at the right edge, where a tall bar can sit under it,
        # so it carries a chip of the chart surface to stay readable. No border:
        # it is a label, not a callout.
        chip = dict(boxstyle="square,pad=0.15", facecolor=t.chart("surface"),
                    edgecolor="none")
        for value, side in ((limit_low, "down"), (limit_high, "up")):
            if value is None:
                continue
            # The wash and the line are both ground, not data: they sit above
            # the gridlines and below every bar, so a bar reading its own status
            # in its own colour is never competing with either.
            tapio_mpl.limit_wash(self.ax, value, side, tapio_mpl.band_color(t),
                                 hatch_color=limit_line)
            self.ax.axhline(y=value, color=limit_line,
                            linewidth=tapio_mpl.LIMIT_WIDTH, zorder=1)
            self.ax.annotate(
                f"{value:g}",
                xy=(1.0, value), xycoords=self.ax.get_yaxis_transform(),
                xytext=(-5, 4 if side == "up" else -4), textcoords="offset points",
                va="bottom" if side == "up" else "top", ha="right",
                fontsize=tapio_mpl.points(t.font_size("eyebrow")), family="monospace",
                color=limit_line, zorder=6, bbox=chip,
            )

        # Get the selected statistic name for y-axis label
        selected_stat_name = _("STATISTIC_VALUE")  # default
        if hasattr(self.parent_widget, 'selected_stat'):
            selected_stat_name = profile_stats.analysis_display_labels.get(
                self.parent_widget.selected_stat,
                selected_stat_name,
            )

        tapio_mpl.finish(
            self.ax,
            xlabel=_("PLOT_TITLE_ROLL"),
            ylabel=selected_stat_name,
        )

        # A categorical axis has no positions to read off it. One tick and one
        # gridline through the centre of every bar, labelled nothing, ruled the
        # panel into stripes the bars had to be read through. A gridline is
        # drawn at a tick, so dropping the ticks drops the vertical rules with
        # them and leaves the horizontal ones the values are read against.
        # After finish(), which turns both axes on; ax.clear() at the top of
        # plot() puts the rcParam defaults back before every redraw.
        self.ax.set_xticks([])
        self.ax.grid(False, axis="x")

        tapio_mpl.fit(self.figure)

        self.canvas.draw()

    def on_hover(self, event):
        vis = self.annot.get_visible()
        if event.inaxes != self.ax:
            if vis:
                self.annot.set_visible(False)
                self.canvas.draw_idle()
            return

        if not hasattr(self, 'bars'):
            return

        for i, bar in enumerate(self.bars):
            cont, _ = bar.contains(event)
            if cont:
                point = self.stat_data[i]
                x_pos = bar.get_x() + bar.get_width() / 2
                self.annot.xy = (x_pos, event.ydata)

                # Check if the tooltip is too close to the right edge
                if event.xdata / self.ax.get_xlim()[1] > 0.8:
                    self.annot.set_ha('right')
                else:
                    self.annot.set_ha('left')

                date_str = datetime.fromtimestamp(point['x']).strftime('%Y-%m-%d %H:%M')
                text = f"{point['label']}\n{date_str}"
                self.annot.set_text(text)
                self.annot.set_visible(True)
                self.canvas.draw_idle()
                return

        if vis:
            self.annot.set_visible(False)
            self.canvas.draw_idle()

    def _draw_info_on_figure(self):
        """Draw selected stat and filter info on the figure.

        Returns:
            List of text objects that were added (for cleanup)
        """
        added_texts = []

        if not self.parent_widget:
            return added_texts

        # Get current stat display name
        stat_display_name = ""
        if hasattr(self.parent_widget, 'selected_stat'):
            stat_display_name = profile_stats.analysis_display_labels.get(
                self.parent_widget.selected_stat,
                "",
            )

        # Get current filter text
        filter_text = ""
        if hasattr(self.parent_widget, 'filter_dropdown'):
            filter_text = self.parent_widget.filter_dropdown.currentText()
        if getattr(self.parent_widget, 'roll_filter_pattern', ""):
            filter_text = f"{filter_text}\n{_('STATISTICS_ROLL_FILTER_LABEL')}: {self.parent_widget.roll_filter_pattern}"

        # Create info text
        info_text = f"{stat_display_name}\n{filter_text}"

        # Position at top right of figure
        t = tapio_mpl.current
        text_obj = self.figure.text(
            0.95, 0.90,
            info_text,
            ha='right', va='top',
            fontsize=tapio_mpl.points(t.font_size("body-sm")),
            color=t.color("ink-secondary"),
            bbox=dict(boxstyle='round,pad=0.5', facecolor=t.color("surface"),
                      edgecolor=t.color("border"), linewidth=1.0),
            transform=self.figure.transFigure,
        )
        added_texts.append(text_obj)

        return added_texts

    def on_pick(self, event):
        if event.artist not in self.bars:
            return True

        # Find which bar was clicked
        bar_index = list(self.bars).index(event.artist)
        point = self.stat_data[bar_index]

        self.highlight_point(point['label'])
        self.point_selected.emit(point['path'])

class StatisticsAnalysisWidget(QWidget):
    directory_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        theme_qt.pad(self.layout(), 2)
        theme_qt.gap(self.layout(), 1)


        # Set to the key value, not the display name
        self.selected_stat = list(stat_label_map.values())[0]  # This will be "mean"

        # Cache for processed roll data
        self.cached_roll_data = []
        self.cache_valid = False
        self.roll_filter_pattern = ""
        self.roll_filter_regex = None

        # Create horizontal layout for dropdowns and refresh button
        # Wrap dropdowns in a container widget so they can be captured together
        self.dropdown_container = QWidget()
        dropdown_layout = QHBoxLayout(self.dropdown_container)
        theme_qt.pad(dropdown_layout, 0)
        theme_qt.gap(dropdown_layout, 4)

        self.stat_selection_dropdown = StatSelectionDropdown(self)
        self.stat_selection_dropdown.currentTextChanged.connect(self.on_stat_selection_changed)

        self.filter_dropdown = FilterDropdown(self)
        self.filter_dropdown.currentTextChanged.connect(self.on_filter_changed)

        # Labels sit above the field, always: a bare control is only legible to
        # whoever configured it.
        for label_text, control in (
            (_("STATISTIC_VALUE"), self.stat_selection_dropdown),
            (_("STATISTICS_TIME_RANGE"), self.filter_dropdown),
        ):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            theme_qt.pad(field_layout, 0)
            theme_qt.gap(field_layout, 1)
            field_layout.addWidget(SectionLabel(label_text))
            field_layout.addWidget(control)
            dropdown_layout.addWidget(field)

        # Add refresh button
        self.refresh_button_layout = QHBoxLayout()
        self.refresh_button = QPushButton(_("BUTTON_TEXT_REFRESH"), self)
        theme_qt.set_variant(self.refresh_button, "ghost")
        self.refresh_button.clicked.connect(self.refresh_data)
        self.refresh_button_layout.addStretch()
        self.refresh_button_layout.addWidget(self.refresh_button)

        # Create stacked widget to switch between loading and chart
        self.stacked_widget = QStackedWidget(self)
        # Qt builds a QStackedLayout of its own here, on its own defaults. The
        # container holds no padding; the pages inside it carry theirs.
        theme_qt.pad(self.stacked_widget.layout(), 0)
        theme_qt.gap(self.stacked_widget.layout(), 0)

        # Create loading widget
        self.loading_widget = LoadingWidget(self)

        # Create chart widget
        self.chart = StatisticsAnalysisChart(self)
        self.chart.point_selected.connect(self.on_point_selected)

        # Add widgets to stacked widget
        self.stacked_widget.addWidget(self.chart)  # index 0
        self.stacked_widget.addWidget(self.loading_widget)  # index 1

        toolbar_layout = QHBoxLayout()
        theme_qt.pad(toolbar_layout, 0)
        toolbar_layout.addWidget(self.dropdown_container)
        toolbar_layout.addStretch()
        toolbar_layout.addLayout(self.refresh_button_layout)

        self.layout().addLayout(toolbar_layout)
        self.layout().addWidget(self.stacked_widget)

        # Initialize worker
        self.processor = StatisticsProcessor(self)
        self.processor.progress.connect(self.on_processing_progress)
        self.processor.finished.connect(self.on_processing_finished)
        self.processor.error.connect(self.on_processing_error)

        self.update()

    @Slot(str)
    def on_stat_selection_changed(self, stat_label: str):
        self.selected_stat = stat_label_map[stat_label]
        self.update_chart()

    @Slot(str)
    def on_filter_changed(self, filter_option: str):
        self.update_chart()

    def set_roll_filter(self, pattern: str, compiled_regex):
        self.roll_filter_pattern = pattern
        self.roll_filter_regex = compiled_regex
        if self.cache_valid and self.isVisible():
            self.update_chart()

    @Slot(str)
    def on_point_selected(self, label: str):
        self.highlight_point(label)
        self.directory_selected.emit(label)

    @Slot(str)
    def highlight_point(self, dir_path: str):
        label = os.path.basename(dir_path)
        self.chart.highlight_point(label)

    @Slot()
    def refresh_data(self):
        """Force refresh of all statistics data."""
        self.cache_valid = False
        self.update()

    @Slot()
    def update(self):
        """Load or refresh data, then update chart."""
        if not self.isVisible():
            return

        # If cache is valid, just filter and update chart
        if self.cache_valid and self.cached_roll_data:
            self.update_chart()
            return

        # Need to load data - stop any existing processing
        if self.processor.is_running():
            self.processor.stop()

        # Show loading widget
        self.loading_widget.reset()
        self.stacked_widget.setCurrentWidget(self.loading_widget)
        self.refresh_button.setEnabled(False)

        # Start processing in worker thread
        self.processor.start(store.root_directory)

    def update_chart(self):
        """Update chart using cached data with current filters."""
        if not self.cache_valid:
            # No cached data, need to load
            self.update()
            return

        # Apply filters to cached data
        filtered_data = self.apply_filters(self.cached_roll_data)

        # Convert to chart format
        chart_data = self.prepare_chart_data(filtered_data)

        # Update chart
        self.chart.plot(chart_data)
        self.stacked_widget.setCurrentWidget(self.chart)

    def apply_filters(self, roll_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply roll-name and time filters to roll data."""
        filtered_data = roll_data
        if self.roll_filter_regex:
            filtered_data = [
                roll for roll in filtered_data
                if self.roll_filter_regex.search(str(roll.get('label', '')))
            ]

        filter_text = self.filter_dropdown.currentText()

        # No time filtering needed for "show all"
        if filter_text == _("FILTER_SHOW_ALL_ROLLS"):
            return filtered_data

        # Calculate cutoff time
        now = datetime.now()
        if filter_text == _("FILTER_LAST_7_DAYS"):
            cutoff = now - timedelta(days=7)
        elif filter_text == _("FILTER_LAST_30_DAYS"):
            cutoff = now - timedelta(days=30)
        else:
            return filtered_data

        cutoff_timestamp = cutoff.timestamp()

        # Filter by timestamp
        return [roll for roll in filtered_data if roll['timestamp'] >= cutoff_timestamp]

    def prepare_chart_data(self, roll_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert roll data to chart format for the selected statistic."""
        chart_data = []
        stat_key = self.selected_stat

        for roll in roll_data:
            stat_value = roll['stats'].get(stat_key)
            if stat_value is not None:
                chart_data.append({
                    'x': roll['timestamp'],
                    'y': stat_value,
                    'label': roll['label'],
                    'path': roll['path']
                })

        return chart_data

    @Slot(int, str)
    def on_processing_progress(self, value: int, status_text: str):
        """Update loading widget with processing progress."""
        self.loading_widget.update_progress(value, status_text)

    @Slot(list)
    def on_processing_finished(self, roll_data: list):
        """Handle completion of statistics processing."""
        # Cache the roll data
        self.cached_roll_data = roll_data
        self.cache_valid = True
        self.refresh_button.setEnabled(True)

        # Update chart with filtered data
        self.update_chart()

    @Slot(str)
    def on_processing_error(self, error_message: str):
        """Handle processing errors."""
        self.refresh_button.setEnabled(True)
        # Switch back to chart view (which will show "No data available")
        self.stacked_widget.setCurrentWidget(self.chart)
        # Could show error dialog here if desired
        print(f"Error processing statistics: {error_message}")

    def closeEvent(self, event):
        """Clean up worker thread when widget is closed."""
        if self.processor:
            self.processor.stop()
        super().closeEvent(event)
