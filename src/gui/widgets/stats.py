from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGridLayout
from PySide6.QtCore import Qt
from utils.profile_stats import Stats
from utils import preferences

stats = Stats()

class StatsWidget(QWidget):
    def __init__(self, data):
        super().__init__()
        self.limits = preferences.alert_limits
        mean_limit  = next((limit for limit in self.limits if limit['name'] == "mean_g"), None)
        stdev_limit = next((limit for limit in self.limits if limit['name'] == "stdev_g"), None)
        cv_limit    = next((limit for limit in self.limits if limit['name'] == "cv_pct"), None)
        min_limit   = next((limit for limit in self.limits if limit['name'] == "min_g"), None)
        max_limit   = next((limit for limit in self.limits if limit['name'] == "max_g"), None)
        pp_limit    = next((limit for limit in self.limits if limit['name'] == "pp_g"), None)

        layout = QGridLayout()
        self.widgets = [
            MeanWidget(data, mean_limit),
            StdWidget(data, stdev_limit),
            CVWidget(data, cv_limit),
            MinWidget(data, min_limit),
            MaxWidget(data, max_limit),
            PeakToPeakWidget(data, pp_limit)
        ]

        for index, widget in enumerate(self.widgets):
            layout.addWidget(widget, 0, index)
            layout.setColumnMinimumWidth(index, 80)

        self.setLayout(layout)  # Set the layout for the StatsWidget

    def update_data(self, data):
        for widget in self.widgets:
            widget.update_data(data)


class StatWidget(QWidget):
    def __init__(self, data, name, units, func, limit):
        super().__init__()
        self.name = name
        self.units = units
        self.func = func
        self.limit = limit
        self.data = data
        self.value = None
        self.over_limit = False

        self.setObjectName("statWidget")

        self.layout = QVBoxLayout()

        self.label = QLabel(f"{self.name} [{self.units}]")
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.label.setStyleSheet("font-size: 12px; background-color: transparent;")
        self.layout.addWidget(self.label)

        self.value_label = QLabel(f"{self.value}")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.value_label.setStyleSheet("font-size: 20px; background-color: transparent;")
        self.layout.addWidget(self.value_label)

        self.setLayout(self.layout)  # Set the layout for the StatWidget

        self.update_data(self.data)

    def update_tooltip(self):
        if self.limit is not None:
            min_val = self.limit['min']
            max_val = self.limit['max']
            tooltip = f"Alert Limits:\nMin: {min_val}\nMax: {max_val}"
        else:
            tooltip = "No alert limits set"
        self.setToolTip(tooltip)

    def update_data(self, data):
        self.data = data
        if len(self.data):
            self.value = self.func(self.data)
            self.over_limit = False

            if self.limit is not None:
                if self.limit['min'] is not None:
                    self.over_limit = self.value < self.limit['min']
                if self.limit['max'] is not None:
                    self.over_limit = self.over_limit or self.value > self.limit['max']

            if self.over_limit:
                self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self.setStyleSheet("""
                    QWidget#statWidget {
                        background-color: rgba(255, 0, 0, 80);
                        border-bottom-style: solid;
                        border-width: 3px;
                        border-color: red;
                    }
                """)
            else:
                self.setStyleSheet("")  # Reset the background color if not over limit

            self.value_label.setText(f"{self.value or 0:.2f}")
            self.update_tooltip()
        else:
            self.value_label.setText("--")

class MeanWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.mean.label, stats.mean.unit, stats.mean, limit)

class StdWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.std.label, stats.std.unit, stats.std, limit)

class CVWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.cv.label, stats.cv.unit, stats.cv, limit)

class MinWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.min.label, stats.min.unit, stats.min, limit)

class MaxWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.max.label, stats.max.unit, stats.max, limit)

class PeakToPeakWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, stats.pp.label, stats.pp.unit, stats.pp, limit)