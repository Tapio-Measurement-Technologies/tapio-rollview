from PySide6.QtWidgets import QWidget, QComboBox, QVBoxLayout, QHBoxLayout, QStackedWidget, QPushButton
from utils.profile_stats import Stats
from PySide6.QtCore import Slot, Signal
import store
import os
from typing import List, Dict, Any
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from datetime import datetime, timedelta
from utils.translation import _
from utils import preferences
from workers.statistics_processor import StatisticsProcessor
from gui.widgets.LoadingWidget import LoadingWidget

chart_point_style = {
    'markersize': 4,
    'color': 'tab:blue'
}

selected_point_style = {
    'markersize': 6,
    'color': 'tab:green'
}

stat_label_map = {
    _("MEAN_LONG") + " [g]": "mean",
    _("STDEV_LONG") + " [g]": "std",
    _("CV_LONG") + " [%]": "cv",
    _("MIN_LONG") + " [g]": "min",
    _("MAX_LONG") + " [g]": "max",
    _("PP_LONG") + " [g]": "pp"
}
stats = Stats()

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
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.stat_data = []
        self.highlighted_point = None

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.canvas.mpl_connect("pick_event", self.on_pick)
        self.canvas.mpl_connect('motion_notify_event', self.on_hover)

    def highlight_point(self, label: str):
        self.highlighted_point = label
        self.plot(self.stat_data)

    def plot(self, stat_data: List[Dict[str, Any]]):
        self.stat_data = stat_data
        self.ax.clear()
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(0,10),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round", fc="w"))
        self.annot.set_visible(False)

        if not stat_data:
            self.ax.text(0.5, 0.5, _("NO_DATA_AVAILABLE"), ha="center", va="center", transform=self.ax.transAxes, fontdict={'size': 16})
            self.ax.axis('off')
            self.canvas.draw()
            return

        # Use enumerated indices for x-axis instead of timestamps
        x_indices = list(range(len(stat_data)))
        y = [p['y'] for p in stat_data]
        labels = [p['label'] for p in stat_data]

        # Add alert limit ranges as shaded areas if available (draw behind bars)
        if hasattr(self.parent(), 'selected_stat'):
            current_stat = self.parent().selected_stat
            # Find matching alert limit by checking if stat name is substring of alert name
            matching_limit = None
            for limit in preferences.alert_limits:
                if current_stat in limit['name']:
                    matching_limit = limit
                    break

            if matching_limit and (matching_limit['min'] is not None or matching_limit['max'] is not None):
                y_min, y_max = self.ax.get_ylim()

                # Add shaded area for acceptable range extending to plot edges (behind bars)
                if matching_limit['min'] is not None and matching_limit['max'] is not None:
                    # Both min and max: shade between them
                    self.ax.axhspan(matching_limit['min'], matching_limit['max'], alpha=0.2, color='grey', zorder=0)
                elif matching_limit['min'] is not None:
                    # Only min: shade above min
                    self.ax.axhspan(matching_limit['min'], y_max, alpha=0.2, color='grey', zorder=0)
                elif matching_limit['max'] is not None:
                    # Only max: shade below max
                    self.ax.axhspan(y_min, matching_limit['max'], alpha=0.2, color='grey', zorder=0)

                # Add threshold lines (also behind bars)
                if matching_limit['min'] is not None:
                    self.ax.axhline(y=matching_limit['min'], color='grey', linestyle='--', alpha=0.7, linewidth=1, zorder=1)
                if matching_limit['max'] is not None:
                    self.ax.axhline(y=matching_limit['max'], color='grey', linestyle='--', alpha=0.7, linewidth=1, zorder=1)

        # Convert to bar chart (draw bars on top with higher zorder)
        bar_width = 0.7
        self.bars = self.ax.bar(x_indices, y, width=bar_width, alpha=1, color='tab:blue', picker=5, zorder=2)

        if self.highlighted_point:
            for i, p in enumerate(stat_data):
                if p['label'] == self.highlighted_point:
                    # Highlight the specific bar
                    self.bars[i].set_color('tab:orange')
                    self.bars[i].set_alpha(1.0)
                    break

        # Formatting
        self.ax.set_xlabel(_("PLOT_TITLE_ROLL"))
        # Get the selected statistic name for y-axis label
        selected_stat_name = "Statistic Value"  # default
        if hasattr(self.parent(), 'selected_stat'):
            # Reverse lookup to get the display name from the key
            for display_name, stat_key in stat_label_map.items():
                if stat_key == self.parent().selected_stat:
                    selected_stat_name = display_name
                    break
        self.ax.set_ylabel(selected_stat_name)

        self.ax.grid(True, axis='y')  # Only show horizontal grid lines for bar charts

        # Set x-axis ticks to show roll labels
        self.ax.set_xticks(x_indices)

        # Only show x-axis labels if there are 20 or fewer rolls
        self.ax.set_xticklabels([])  # Hide labels

        self.figure.tight_layout()

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

    def on_pick(self, event):
        vis = self.annot.get_visible()
        if event.artist not in self.bars:
            return True

        # Find which bar was clicked
        bar_index = list(self.bars).index(event.artist)
        point = self.stat_data[bar_index]

        self.point_selected.emit(point['path'])

class StatisticsAnalysisWidget(QWidget):
    directory_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        # Set to the key value, not the display name
        self.selected_stat = list(stat_label_map.values())[0]  # This will be "mean"

        # Cache for processed roll data
        self.cached_roll_data = []
        self.cache_valid = False

        # Create horizontal layout for dropdowns and refresh button
        dropdown_layout = QHBoxLayout()

        self.stat_selection_dropdown = StatSelectionDropdown(self)
        self.stat_selection_dropdown.currentTextChanged.connect(self.on_stat_selection_changed)

        self.filter_dropdown = FilterDropdown(self)
        self.filter_dropdown.currentTextChanged.connect(self.on_filter_changed)

        dropdown_layout.addWidget(self.stat_selection_dropdown)
        dropdown_layout.addWidget(self.filter_dropdown)

        # Add refresh button
        self.refresh_button_layout = QHBoxLayout()
        self.refresh_button = QPushButton(_("BUTTON_TEXT_REFRESH"), self)
        self.refresh_button.clicked.connect(self.refresh_data)
        self.refresh_button_layout.addStretch()
        self.refresh_button_layout.addWidget(self.refresh_button)

        # Create stacked widget to switch between loading and chart
        self.stacked_widget = QStackedWidget(self)

        # Create loading widget
        self.loading_widget = LoadingWidget(self)

        # Create chart widget
        self.chart = StatisticsAnalysisChart(self)
        self.chart.point_selected.connect(self.on_point_selected)

        # Add widgets to stacked widget
        self.stacked_widget.addWidget(self.chart)  # index 0
        self.stacked_widget.addWidget(self.loading_widget)  # index 1

        self.layout().addLayout(dropdown_layout)
        self.layout().addLayout(self.refresh_button_layout)
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

    @Slot(str)
    def on_point_selected(self, label: str):
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
        if not self.cache_valid or not self.cached_roll_data:
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
        """Apply time filter to roll data."""
        filter_text = self.filter_dropdown.currentText()

        # No time filtering needed for "show all"
        if filter_text == _("FILTER_SHOW_ALL_ROLLS"):
            return roll_data

        # Calculate cutoff time
        now = datetime.now()
        if filter_text == _("FILTER_LAST_7_DAYS"):
            cutoff = now - timedelta(days=7)
        elif filter_text == _("FILTER_LAST_30_DAYS"):
            cutoff = now - timedelta(days=30)
        else:
            return roll_data

        cutoff_timestamp = cutoff.timestamp()

        # Filter by timestamp
        return [roll for roll in roll_data if roll['timestamp'] >= cutoff_timestamp]

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