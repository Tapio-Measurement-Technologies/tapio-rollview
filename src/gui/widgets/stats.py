from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGridLayout, QMenu, QApplication
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
import settings
from utils.profile_stats import Stats
from utils import preferences, profile_stats
from utils.translation import _
from .AlertLimitEditor import AlertLimitEditor

stats = Stats()


def format_stat_value(value):
    return f"{value:.{settings.STAT_DECIMAL_PLACES}f}"


def has_stat_data(data):
    if isinstance(data, tuple) and len(data) == 2:
        return len(data[1]) > 0
    return len(data) > 0

class StatsWidget(QWidget):
    def __init__(self, data):
        super().__init__()
        self.limits = preferences.alert_limits
        limit_map = {limit.get('name'): limit for limit in self.limits}

        self.layout = QGridLayout()
        self.layout.setContentsMargins(4, 1, 4, 1)
        self.layout.setHorizontalSpacing(6)
        self.layout.setVerticalSpacing(3)
        self.widgets = [
            MeanWidget(data, limit_map.get(stats.mean.name)),
            StdWidget(data, limit_map.get(stats.std.name)),
            CVWidget(data, limit_map.get(stats.cv.name)),
            MinWidget(data, limit_map.get(stats.min.name)),
            MaxWidget(data, limit_map.get(stats.max.name)),
            PeakToPeakWidget(data, limit_map.get(stats.pp.name)),
            SlopeWidget(data, limit_map.get(stats.slope.name)),
        ]
        self._column_count = 0
        self._min_cell_width = max(widget.sizeHint().width() for widget in self.widgets)

        self.setLayout(self.layout)  # Set the layout for the StatsWidget
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self._relayout_widgets()

    def _calculate_columns(self):
        available_width = max(self.width(), self.sizeHint().width(), self._min_cell_width)
        return max(1, available_width // self._min_cell_width)

    def _relayout_widgets(self):
        column_count = min(len(self.widgets), self._calculate_columns())
        if column_count == self._column_count:
            return

        while self.layout.count():
            self.layout.takeAt(0)

        self._column_count = column_count

        for column in range(column_count):
            self.layout.setColumnMinimumWidth(column, self._min_cell_width)

        for index, widget in enumerate(self.widgets):
            row = index // column_count
            column = index % column_count
            self.layout.addWidget(widget, row, column)

    def resizeEvent(self, event):
        self._relayout_widgets()
        super().resizeEvent(event)

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
                stats_text.append(f"{widget.name}: {format_stat_value(widget.value)} {widget.units}")
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
        self.layout.setContentsMargins(6, 3, 6, 3)
        self.layout.setSpacing(3)

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
        if has_stat_data(self.data):
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

            self.value_label.setText(format_stat_value(self.value or 0))
            self.update_tooltip()
        else:
            self.value_label.setText("--")

class MeanWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.mean.name, stats.mean.name), stats.mean.unit, stats.mean, limit)

class StdWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.std.name, stats.std.name), stats.std.unit, stats.std, limit)

class CVWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.cv.name, stats.cv.name), stats.cv.unit, stats.cv, limit)

class MinWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.min.name, stats.min.name), stats.min.unit, stats.min, limit)

class MaxWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.max.name, stats.max.name), stats.max.unit, stats.max, limit)

class PeakToPeakWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.pp.name, stats.pp.name), stats.pp.unit, stats.pp, limit)

class SlopeWidget(StatWidget):
    def __init__(self, data, limit=None):
        super().__init__(data, profile_stats.stat_labels.get(stats.slope.name, stats.slope.name), stats.slope.unit, stats.slope, limit)
