from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGridLayout, QMenu, QApplication
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
from utils.profile_stats import Stats
from utils import preferences, profile_stats
from utils.translation import _
from .AlertLimitEditor import AlertLimitEditor

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
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        """Show context menu with option to copy stats to clipboard."""
        context_menu = QMenu(self)

        copy_action = QAction(_("COPY_STATS_TO_CLIPBOARD"), self)
        copy_action.triggered.connect(self.copy_stats_to_clipboard)
        context_menu.addAction(copy_action)

        context_menu.exec_(self.mapToGlobal(position))

    def copy_stats_to_clipboard(self):
        """Copy all statistics to clipboard as formatted text."""
        stats_text = []
        for widget in self.widgets:
            if widget.value is not None:
                stats_text.append(f"{widget.name}: {widget.value:.2f} {widget.units}")
            else:
                stats_text.append(f"{widget.name}: --")

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(stats_text))
        print("Statistics copied to clipboard.")

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
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_alert_limit_editor()
        super().mousePressEvent(event)

    def open_alert_limit_editor(self):
        # Find the stat name from the function
        stat_name = getattr(self.func, 'name', None)
        if stat_name:
            editor = AlertLimitEditor(stat_name, self.limit, self)
            if editor.exec() == AlertLimitEditor.DialogCode.Accepted:
                # Reload preferences and update the limit
                self.limit = next((limit for limit in preferences.alert_limits if limit['name'] == stat_name), None)
                self.update_data(self.data)  # Refresh the widget display

    def update_tooltip(self):
        if self.limit is not None:
            min_val = self.limit['min']
            max_val = self.limit['max']
            tooltip = f"{_("ALERT_LIMITS")}:\n{_("MIN")}: {min_val}\n{_("MAX")}: {max_val}"
        else:
            tooltip = _("ALERT_LIMITS_NOT_SET")
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
        super().__init__(data, profile_stats.stat_labels[stats.mean.name], stats.mean.unit, stats.mean, limit)

class StdWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels[stats.std.name], stats.std.unit, stats.std, limit)

class CVWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels[stats.cv.name], stats.cv.unit, stats.cv, limit)

class MinWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels[stats.min.name], stats.min.unit, stats.min, limit)

class MaxWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels[stats.max.name], stats.max.unit, stats.max, limit)

class PeakToPeakWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels[stats.pp.name], stats.pp.unit, stats.pp, limit)