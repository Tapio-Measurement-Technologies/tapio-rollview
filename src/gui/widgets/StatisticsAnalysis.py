from PySide6.QtWidgets import QWidget, QComboBox, QVBoxLayout
from models.Profile import RollDirectory
from utils.profile_stats import Stats
from PySide6.QtCore import Slot
import store
import os
from typing import List, Dict, Any
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from datetime import datetime

stat_label_map = {
    "Mean": "mean",
    "Standard deviation": "std",
    "Coefficient of variation": "cv",
    "Minimum": "min",
    "Maximum": "max",
    "Peak to peak": "pp"
}
stats = Stats()

class StatSelectionDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(list(stat_label_map.keys()))

class StatisticsAnalysisChart(QWidget):
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

    def on_pick(self, event):
        vis = self.annot.get_visible()
        if event.artist != self.line:
            return True

        ind = event.ind[0]
        point = self.stat_data[ind]
        self.annot.xy = (datetime.fromtimestamp(point['x']), point['y'])
        self.annot.set_text(point['label'])
        self.annot.set_visible(True)
        self.canvas.draw_idle()

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

        x = [datetime.fromtimestamp(p['x']) for p in stat_data]
        y = [p['y'] for p in stat_data]

        self.line, = self.ax.plot(x, y, 'o-', picker=5)

        if self.highlighted_point:
            for i, p in enumerate(stat_data):
                if p['label'] == self.highlighted_point:
                    self.ax.plot(x[i], y[i], 'o', color='tab:red', markersize=8)
                    break

        # Formatting
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Statistic Value")
        self.ax.grid(True)
        self.figure.tight_layout()

        self.canvas.draw()

class StatisticsAnalysisWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        self.selected_stat = list(stat_label_map.keys())[0]

        self.stat_selection_dropdown = StatSelectionDropdown(self)
        self.stat_selection_dropdown.currentTextChanged.connect(self.on_stat_selection_changed)
        self.chart = StatisticsAnalysisChart(self)

        self.layout().addWidget(self.stat_selection_dropdown)
        self.layout().addWidget(self.chart)

        self.update()

    @Slot(str)
    def on_stat_selection_changed(self, stat_label: str):
        self.selected_stat = stat_label_map[stat_label]
        self.update()

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

        for roll_dir in roll_directories:
            if roll_dir.mean_profile is not None and len(roll_dir.mean_profile) > 0:
                y = stat_func(roll_dir.mean_profile)
                x = roll_dir.newest_timestamp
                label = os.path.basename(roll_dir.path)
                points.append({'x': x, 'y': y, 'label': label})

        points.sort(key=lambda p: p['x'])
        return points