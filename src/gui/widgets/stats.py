from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QMenu, QApplication
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, Signal
import settings
import theme
from theme import qt as theme_qt
from utils.profile_stats import Stats
from utils import preferences, profile_stats
from utils.translation import _
from theme.widgets import EyebrowLabel
from .AlertLimitEditor import AlertLimitEditor

stats = Stats()

MISSING = "—"  # Missing is an em dash, not 0, not blank, not NaN. Zero is a measurement.


def format_stat_value(value):
    return f"{value:.{settings.STAT_DECIMAL_PLACES}f}"


def has_stat_data(data):
    if isinstance(data, tuple) and len(data) == 2:
        return len(data[1]) > 0
    return len(data) > 0


def verdict_for(widgets):
    """The verdict for a whole run, from the tiles that make it up.

    ``bad`` if any statistic crossed its limit, ``good`` if limits are
    configured and everything is inside them, ``idle`` when there is nothing to
    judge — no data, or no limits configured for any statistic.
    """
    measured = [w for w in widgets if w.value is not None]
    if not measured:
        return theme.STATUS_IDLE
    if any(w.over_limit for w in measured):
        return theme.STATUS_BAD
    if any(w.has_limit() for w in measured):
        return theme.STATUS_GOOD
    return theme.STATUS_IDLE


class StatsWidget(QWidget):
    """The row of stat tiles that sits above the chart.

    The verdict on a run should be readable without parsing a plot, so the
    tiles come first and the chart second.
    """

    verdict_changed = Signal(str)

    def __init__(self, data):
        super().__init__()
        limit_map = self._get_limit_map()

        tokens = theme_qt.tokens()
        self.layout = QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, tokens.space(2))
        self.layout.setHorizontalSpacing(tokens.space(2))
        self.layout.setVerticalSpacing(tokens.space(2))
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
        self._min_cell_width = 0
        self._measure_cells()

        self.setLayout(self.layout)  # Set the layout for the StatsWidget
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self._relayout_widgets()

    def verdict(self):
        return verdict_for(self.widgets)

    def _get_limit_map(self):
        return {limit.get('name'): limit for limit in preferences.alert_limits}

    def _refresh_limits(self):
        limit_map = self._get_limit_map()
        for widget in self.widgets:
            stat_name = getattr(widget.func, 'name', None)
            widget.limit = limit_map.get(stat_name)

    def _measure_cells(self):
        """Re-measure the widest tile.

        Worth doing every time the data changes: the footer under the number
        grows when a limit is crossed ("Below lower limit 34.0" is a good deal
        wider than "Limits 34.0 – 46.0"), and a width measured while the tiles
        were still empty clips exactly the message that matters most.
        """
        for widget in self.widgets:
            # sizeHint() is cached until the layout is activated, so a tile
            # measured straight after setText() still reports its old width.
            # (`widget.layout` is the attribute these classes assign, not
            # QWidget.layout() — the name is shadowed throughout this file.)
            widget.layout.activate()
            widget.updateGeometry()
        width = max(widget.sizeHint().width() for widget in self.widgets)
        if width == self._min_cell_width:
            return False
        self._min_cell_width = width
        self._column_count = 0
        return True

    def _calculate_columns(self):
        # Only the real width counts. Folding sizeHint() in makes the answer
        # self-fulfilling: the hint is the sum of the columns already laid out,
        # so it always says the current column count fits — even when the tiles
        # are being squeezed narrower than their content.
        available_width = self.width()
        if available_width <= 0:
            available_width = self._min_cell_width
        spacing = self.layout.horizontalSpacing()
        return max(1, (available_width + spacing) // (self._min_cell_width + spacing))

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
                stats_text.append(f"{widget.name}: {MISSING}")

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(stats_text))
        print("Statistics copied to clipboard.")

    def update_data(self, data):
        self._refresh_limits()
        for widget in self.widgets:
            widget.update_data(data)
        self._measure_cells()
        self._relayout_widgets()
        self.verdict_changed.emit(self.verdict())


class StatWidget(QWidget):
    """One stat tile: eyebrow label, the number in mono, the limit beneath it.

    Only the failing tile turns red. A row of red tiles tells the operator
    nothing about *which* statistic failed.
    """

    def __init__(self, data, name, units, func, limit):
        super().__init__()
        self.name = name
        self.units = units
        self.func = func
        self.limit = limit
        self.data = data
        self.value = None
        self.over_limit = False

        self.setObjectName("statTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        tokens = theme_qt.tokens()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(
            tokens.space(3), tokens.space(2), tokens.space(3), tokens.space(2)
        )
        self.layout.setSpacing(tokens.space(1))

        # Eyebrow: mono, uppercase, muted.
        self.label = EyebrowLabel(self.name)
        self.layout.addWidget(self.label)

        # The number and its unit are separate: the number is the signal, the
        # unit is one step smaller and muted, and never bold.
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(tokens.space(1))
        value_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBaseline)

        self.value_label = QLabel(MISSING)
        theme_qt.set_role(self.value_label, "dataLarge")
        value_row.addWidget(self.value_label)

        self.unit_label = QLabel(self.units)
        theme_qt.set_role(self.unit_label, "unit")
        value_row.addWidget(self.unit_label)
        value_row.addStretch(1)
        self.layout.addLayout(value_row)

        # The limit is stated on the tile, not only in a tooltip: there is no
        # hover on a mill-floor tablet, and hover-only information is invisible
        # to anyone who does not go looking for it.
        self.foot_label = QLabel()
        theme_qt.set_role(self.foot_label, "hint")
        self.layout.addWidget(self.foot_label)

        self.setLayout(self.layout)  # Set the layout for the StatWidget

        self.update_data(self.data)

    def has_limit(self):
        return self.limit is not None and (
            self.limit.get('min') is not None or self.limit.get('max') is not None
        )

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

    def _foot_text(self):
        """What the tile says under the number: the limit, or why it failed."""
        if not self.has_limit():
            return _("STAT_TILE_NO_LIMITS")

        minimum = self.limit.get('min')
        maximum = self.limit.get('max')

        if self.value is not None:
            if minimum is not None and self.value < minimum:
                return _("STAT_TILE_BELOW_MIN").format(value=format_stat_value(minimum))
            if maximum is not None and self.value > maximum:
                return _("STAT_TILE_ABOVE_MAX").format(value=format_stat_value(maximum))

        if minimum is not None and maximum is not None:
            return _("STAT_TILE_LIMIT_RANGE").format(
                min=format_stat_value(minimum), max=format_stat_value(maximum)
            )
        if minimum is not None:
            return _("STAT_TILE_LIMIT_MIN").format(value=format_stat_value(minimum))
        return _("STAT_TILE_LIMIT_MAX").format(value=format_stat_value(maximum))

    def update_tooltip(self):
        if self.has_limit():
            min_val = self.limit['min']
            max_val = self.limit['max']
            tooltip = f"{_('ALERT_LIMITS')}:\n{_('MIN')}: {min_val}\n{_('MAX')}: {max_val}"
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

            self.value_label.setText(format_stat_value(self.value or 0))
            self.unit_label.setText(self.units)
        else:
            self.value = None
            self.over_limit = False
            self.value_label.setText(MISSING)
            self.unit_label.setText(self.units)

        state = theme.STATUS_BAD if self.over_limit else None
        theme_qt.set_state(self, state)
        theme_qt.set_state(self.value_label, state)
        theme_qt.set_state(self.foot_label, state)
        self.foot_label.setText(self._foot_text())
        self.update_tooltip()

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
