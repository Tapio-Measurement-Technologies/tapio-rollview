from PySide6.QtWidgets import QWidget, QComboBox, QVBoxLayout, QHBoxLayout
from models.Profile import RollDirectory
from utils.profile_stats import Stats
from PySide6.QtCore import Slot, Signal
import store
import os
from typing import List, Dict, Any
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from datetime import datetime, timedelta

chart_point_style = {
    'markersize': 4,
    'color': 'tab:blue'
}

selected_point_style = {
    'markersize': 6,
    'color': 'tab:green'
}

stat_label_map = {
    "Mean [g]": "mean",
    "Standard deviation [g]": "std",
    "Coefficient of variation [%]": "cv",
    "Minimum [g]": "min",
    "Maximum [g]": "max",
    "Peak to peak [g]": "pp"
}
stats = Stats()

class StatSelectionDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(list(stat_label_map.keys()))

class FilterDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(["Last 7 days", "Last 30 days", "Show all rolls"])
        self.setCurrentText("Last 7 days")

class StatisticsAnalysisChart(QWidget):
    point_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(20,20),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round", fc="w"),
                    arrowprops=dict(arrowstyle="->"))
        self.annot.set_visible(False)
        self.stat_data = []
        self.highlighted_point = None

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.canvas.mpl_connect("pick_event", self.on_pick)

    def highlight_point(self, label: str):
        self.highlighted_point = label
        self.plot(self.stat_data)

    def plot(self, stat_data: List[Dict[str, Any]]):
        self.stat_data = stat_data
        self.ax.clear()
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(20,20),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round", fc="w"),
                            arrowprops=dict(arrowstyle="->"))
        self.annot.set_visible(False)

        if not stat_data:
            self.canvas.draw()
            return

        # Use enumerated indices for x-axis instead of timestamps
        x_indices = list(range(len(stat_data)))
        y = [p['y'] for p in stat_data]
        labels = [p['label'] for p in stat_data]

        # Adjust bar width based on number of rolls
        num_rolls = len(stat_data)
        bar_width = 0.7

        # Convert to bar chart
        bars = self.ax.bar(x_indices, y, width=bar_width, alpha=0.7, color='tab:blue', picker=5)
        
        # Store bars for picker functionality
        self.bars = bars

        if self.highlighted_point:
            for i, p in enumerate(stat_data):
                if p['label'] == self.highlighted_point:
                    # Highlight the specific bar
                    bars[i].set_color('tab:orange')
                    bars[i].set_alpha(1.0)
                    break

        # Formatting
        self.ax.set_xlabel("Roll")
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
        if num_rolls <= 20:
            self.ax.set_xticklabels(labels, rotation=45, ha='right')
        else:
            self.ax.set_xticklabels([])  # Hide labels
        
        self.figure.tight_layout()

        self.canvas.draw()

    def on_pick(self, event):
        vis = self.annot.get_visible()
        if event.artist not in self.bars:
            return True

        # Find which bar was clicked
        bar_index = list(self.bars).index(event.artist)
        point = self.stat_data[bar_index]
        
        # Get bar position for annotation
        bar = event.artist
        x_pos = bar.get_x() + bar.get_width() / 2
        y_pos = bar.get_height()
        
        self.annot.xy = (x_pos, y_pos)
        # self.annot.set_text(point['label'])
        # self.annot.set_visible(True)
        self.canvas.draw_idle()
        self.point_selected.emit(point['path'])

class StatisticsAnalysisWidget(QWidget):
    directory_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        # Set to the key value, not the display name
        self.selected_stat = list(stat_label_map.values())[0]  # This will be "mean"

        # Create horizontal layout for dropdowns
        dropdown_layout = QHBoxLayout()
        
        self.stat_selection_dropdown = StatSelectionDropdown(self)
        self.stat_selection_dropdown.currentTextChanged.connect(self.on_stat_selection_changed)
        
        self.filter_dropdown = FilterDropdown(self)
        self.filter_dropdown.currentTextChanged.connect(self.on_filter_changed)
        
        dropdown_layout.addWidget(self.stat_selection_dropdown)
        dropdown_layout.addWidget(self.filter_dropdown)
        
        self.chart = StatisticsAnalysisChart(self)
        self.chart.point_selected.connect(self.on_point_selected)

        self.layout().addLayout(dropdown_layout)
        self.layout().addWidget(self.chart)

        self.update()

    @Slot(str)
    def on_stat_selection_changed(self, stat_label: str):
        self.selected_stat = stat_label_map[stat_label]
        self.update()

    @Slot(str)
    def on_filter_changed(self, filter_option: str):
        self.update()

    @Slot(str)
    def on_point_selected(self, label: str):
        self.directory_selected.emit(label)

    @Slot(str)
    def highlight_point(self, dir_path: str):
        label = os.path.basename(dir_path)
        self.chart.highlight_point(label)

    @Slot()
    def update(self):
        if not self.isVisible():
            return

        paths_in_root_dir = [os.path.join(store.root_directory, d) for d in os.listdir(store.root_directory)]
        dir_paths_in_root_dir = [d for d in paths_in_root_dir if os.path.isdir(d)]
        store.roll_directories = [RollDirectory(d) for d in dir_paths_in_root_dir]
        stat_data = self.get_roll_stat_data(store.roll_directories, self.selected_stat)
        self.chart.plot(stat_data)

    def get_roll_stat_data(self, roll_directories: List[RollDirectory], stat: str):
        points = []
        stat_key = stat.lower()
        try:
            stat_func = getattr(stats, stat_key)
        except AttributeError:
            print(f"Unknown stat: {stat}")
            return []

        # Get current time for filtering
        now = datetime.now()
        
        for roll_dir in roll_directories:
            if roll_dir.mean_profile is not None and len(roll_dir.mean_profile) > 0:
                # Apply time filter
                roll_time = datetime.fromtimestamp(roll_dir.newest_timestamp)
                
                # Check if roll should be included based on filter
                include_roll = True
                filter_option = self.filter_dropdown.currentText()
                
                if filter_option == "Last 7 days":
                    if roll_time < (now - timedelta(days=7)):
                        include_roll = False
                elif filter_option == "Last 30 days":
                    if roll_time < (now - timedelta(days=30)):
                        include_roll = False
                
                if include_roll:
                    y = stat_func(roll_dir.mean_profile)
                    x = roll_dir.newest_timestamp
                    label = os.path.basename(roll_dir.path)
                    points.append({'x': x, 'y': y, 'label': label, 'path': roll_dir.path})

        points.sort(key=lambda p: p['x'])
        return points