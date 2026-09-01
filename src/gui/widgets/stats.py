from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QMenu, QApplication, QSizePolicy
from PySide6.QtGui import QAction, QFontMetrics
from PySide6.QtCore import Qt, QEvent, QSize, Signal
import settings
import theme
from theme import qt as theme_qt
from utils.profile_stats import Stats
from utils import preferences, profile_stats
from utils.translation import _
from theme.widgets import EyebrowLabel
from theme.guidance import set_guidance_everywhere
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


class ElidedLabel(QLabel):
    """A label that shortens its text to the width it is given.

    Used for the limit line under a stat: it should say as much as fits and no
    more, rather than dictating how wide the tile is. The full text stays in the
    accessible name, and the tile states it in the guidance row at the foot of
    the window, which has room a 120 px tile never will.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setText(text)

    def setText(self, text):
        self._full_text = text or ""
        self.setAccessibleName(self._full_text)
        self._apply_elide()

    def text(self):
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        # A repolish changes the two things the elide was computed from — the
        # font, and the box the style sheet puts around the text — and changes
        # neither the widget's width nor its text, so nothing else asks for the
        # elide to be run again. What is left is a string measured under the old
        # rules inside a label that no longer fits it, and QLabel draws that by
        # cutting the end off with no ellipsis to admit it. A bound losing its
        # tail is a different number: "≤ 40.0" reads as "≤ 40".
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
        ):
            self.updateGeometry()
            self._apply_elide()

    def box_width(self):
        """The horizontal space the style sheet's padding and border take.

        Qt reports a style sheet's padding and border on a QLabel as contents
        margins, and QLabel's own sizeHint adds them. Anything that measures the
        text has to account for them too, or it hands the label a width the text
        does not actually get.
        """
        margins = self.contentsMargins()
        return margins.left() + margins.right()

    def _apply_elide(self):
        metrics = QFontMetrics(self.font())
        # The content rect, not the widget rect: the text is painted inside the
        # box, so measuring against the whole widget quietly overruns a padded
        # label by exactly the padding and lets QLabel clip it.
        available = max(self.contentsRect().width(), 0)
        if not available or metrics.horizontalAdvance(self._full_text) <= available:
            # Say it in full whenever it fits. elidedText() measures through the
            # text engine and horizontalAdvance() sums glyph advances, and the
            # two disagree by a pixel on a bold string — enough for a bound
            # given exactly the width it asked for to come back as "≤ 40…",
            # which is a limit the operator cannot read.
            QLabel.setText(self, self._full_text)
            return
        QLabel.setText(
            self, metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available)
        )


class ElidedChunk(ElidedLabel):
    """One run of the limit footer, able to carry its own style property.

    ``ElidedLabel`` is Ignored horizontally, which is right for a lone label
    filling a row and wrong inside a box layout — a row of Ignored items
    collapses to nothing. This asks for the width of its text and accepts none
    of it, so the row packs left, shrinks under pressure and elides rather than
    widening the tile the way a plain QLabel would.

    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        # Measured from the full text, not from the elided string QLabel is
        # currently holding: sizing from what is painted is a ratchet — one
        # squeeze shortens the text, the shorter text asks for less, and the
        # chunk never grows back when the tile does.
        metrics = QFontMetrics(self.font())
        # One pixel of slack, for the same disagreement between the two ways of
        # measuring a string: asking for exactly the advance is asking to be
        # elided by a rounding error. The style box is asked for on top of the
        # text, the way QLabel's own hint counts it.
        return QSize(
            metrics.horizontalAdvance(self.text()) + 1 + self.box_width(),
            super().sizeHint().height(),
        )

    def minimumSizeHint(self):
        # Down to the box and nothing else: the padding is not text and cannot
        # be elided away.
        return QSize(self.box_width(), super().minimumSizeHint().height())


class LimitFooter(QWidget):
    """The limit line under a stat value.

    It always states the limits, in one shape whatever the value did: an
    operator reading a row of tiles should not have to notice that this tile's
    footer switched vocabulary. What changes when a bound is crossed is which
    bound is emphasised — the tile is already the alarm, so the footer's job is
    to say *which end* of the range the value left.

    The bounds are given without a word in front of them. Seven tiles have to
    fit across one row, and a label that elides to "Limi…" spends the width the
    numbers need in order to say something the operator can already see from
    where the line sits.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("limitFooter")
        row = QHBoxLayout(self)
        theme_qt.pad(row, 0)
        theme_qt.gap(row, 1)

        self.min_chunk = ElidedChunk()
        self.max_chunk = ElidedChunk()
        for chunk in (self.min_chunk, self.max_chunk):
            theme_qt.set_role(chunk, "hint")
            row.addWidget(chunk)
        row.addStretch(1)

    def set_limits(self, minimum, maximum, breached=None):
        """State the limits. *breached* is ``"min"``, ``"max"`` or None."""
        if minimum is None and maximum is None:
            # Missing is an em dash here too: an unset limit is not a limit of
            # zero, and seven tiles each spelling out a sentence about it was
            # the noise this replaces.
            self.min_chunk.setText(MISSING)
            self.max_chunk.setText("")
        else:
            lower = (
                _("STAT_TILE_LIMIT_MIN").format(value=format_stat_value(minimum))
                if minimum is not None else ""
            )
            # The separator rides on the lower bound rather than standing as a
            # chunk of its own: a chunk gets the row's gap on both sides, which
            # put a space in front of the comma.
            if lower and maximum is not None:
                lower += _("STAT_TILE_LIMIT_SEPARATOR")
            self.min_chunk.setText(lower)
            self.max_chunk.setText(
                _("STAT_TILE_LIMIT_MAX").format(value=format_stat_value(maximum))
                if maximum is not None else ""
            )

        for chunk in (self.min_chunk, self.max_chunk):
            chunk.setVisible(bool(chunk.text()))

        theme_qt.set_property(self.min_chunk, "limit",
                              "breached" if breached == "min" else None)
        theme_qt.set_property(self.max_chunk, "limit",
                              "breached" if breached == "max" else None)

        self.setAccessibleName(self.text())

    def text(self):
        """The whole line, for the accessible name and for the tests."""
        parts = [self.min_chunk.text(), self.max_chunk.text()]
        return " ".join(part for part in parts if part)


class StatsWidget(QWidget):
    """The row of stat tiles that sits above the chart.

    The verdict on a run should be readable without parsing a plot, so the
    tiles come first and the chart second.
    """

    verdict_changed = Signal(str)
    #: A limit was edited on one of the tiles.
    limits_changed = Signal()

    def __init__(self, data):
        super().__init__()
        self.data = data
        limit_map = self._get_limit_map()

        self.layout = QGridLayout()
        theme_qt.pad(self.layout, 0)
        theme_qt.gap(self.layout, 1, 1)
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
        for widget in self.widgets:
            widget.limit_edited.connect(self.on_limit_edited)
        self._relayout_widgets()

    def on_limit_edited(self):
        """A limit edited on one tile changes the verdict for the whole run.

        The tile that opened the editor refreshes itself, but the run's verdict
        — and the chart's limit lines, which come from the minimum and the
        maximum — belong to everything above this widget, so the change has to
        travel back out.
        """
        self.update_data(self.data)
        self.limits_changed.emit()

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
        """Re-measure the widest tile, by its label and its number.

        The footer is left out on purpose — it elides — so the row stays one
        line however long a limit message gets.
        """
        width = max(widget.content_width() for widget in self.widgets)
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

    def changeEvent(self, event):
        super().changeEvent(event)
        # The column width is measured from a label and a number, so it is only
        # true for the font they were measured in. A theme switch repolishes the
        # tree and can hand every tile a different face without resizing
        # anything, which leaves the row laid out to the old measurement — tiles
        # too narrow for their own numbers, and no event that would ever put it
        # right again.
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
        ):
            if self._measure_cells():
                self._relayout_widgets()

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
        self.data = data
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

    #: This tile's limit was changed in the editor it opened.
    limit_edited = Signal()

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

        self.layout = QVBoxLayout()
        theme_qt.pad(self.layout, 2, 1)
        theme_qt.gap(self.layout, 0)

        # Eyebrow: mono, uppercase, muted.
        self.label = EyebrowLabel(self.name)
        self.layout.addWidget(self.label)

        # The number and its unit are separate: the number is the signal, the
        # unit is one step smaller and muted, and never bold.
        value_row = QHBoxLayout()
        theme_qt.pad(value_row, 0)
        theme_qt.gap(value_row, 1)
        value_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBaseline)

        self.value_label = QLabel(MISSING)
        theme_qt.set_role(self.value_label, "dataValue")
        value_row.addWidget(self.value_label)

        self.unit_label = QLabel(self.units)
        theme_qt.set_role(self.unit_label, "unit")
        value_row.addWidget(self.unit_label)
        value_row.addStretch(1)
        self.layout.addLayout(value_row)

        # The limit is stated on the tile, not only in a tooltip: there is no
        # hover on a mill-floor tablet, and hover-only information is invisible
        # to anyone who does not go looking for it. It elides rather than
        # widening the tile — seven statistics have to fit across one row, and
        # the chart is what the space is for.
        self.foot_label = LimitFooter()
        self.layout.addWidget(self.foot_label)

        self.setLayout(self.layout)  # Set the layout for the StatWidget

        self.update_data(self.data)

    def content_width(self):
        """The width the tile needs for its label and its number.

        Deliberately not the footer's width: the footer is context and elides,
        and sizing every tile to the longest limit message is what pushed the
        row onto two lines and squeezed the plot.
        """
        return max(
            self.label.sizeHint().width(),
            self.value_label.sizeHint().width() + self.unit_label.sizeHint().width() + 3,
        ) + self.layout.contentsMargins().left() + self.layout.contentsMargins().right()

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
            # Parented to the window, not to this tile. The sheet paints a
            # failing tile's labels red through an ancestor selector, and a
            # dialog parented to the tile is inside that ancestor — which put
            # "Lower" and "Upper" in alarm red in a dialog that is not an
            # alarm. A dialog is a window; it belongs to the window.
            editor = AlertLimitEditor(stat_name, self.limit, self.window())
            if editor.exec() == AlertLimitEditor.DialogCode.Accepted:
                # Reload preferences and update the limit
                self.limit = next((limit for limit in preferences.alert_limits if limit['name'] == stat_name), None)
                self.update_data(self.data)  # Refresh the widget display
                self.limit_edited.emit()

    def _breached_bound(self):
        """Which end of the range the value went out of, if either."""
        if self.value is None or not self.has_limit():
            return None

        minimum = self.limit.get('min')
        maximum = self.limit.get('max')
        if minimum is not None and self.value < minimum:
            return "min"
        if maximum is not None and self.value > maximum:
            return "max"
        return None

    def update_guidance(self):
        """What the tile is, what its limits are, and that a click edits them.

        The last part is the reason this line exists: the tile is a button that
        does not look like one, and the pointing-hand cursor is the only other
        thing that says so. The limits are in it because the footer under the
        number elides on a narrow tile, and this row has more room than a tile
        ever will.

        They are read off the footer rather than formatted a second time here,
        so the row and the line under the number cannot come to disagree about
        how a bound is written.
        """
        if self.has_limit():
            detail = _("GUIDANCE_ALERT_LIMITS").format(limits=self.foot_label.text())
        else:
            detail = _("ALERT_LIMITS_NOT_SET")
        # On every label inside the tile as well: Qt emits the status tip of
        # the widget the pointer entered and asks no parent, and the number and
        # the limit line cover most of the tile.
        set_guidance_everywhere(self, self.name, detail,
                                _("GUIDANCE_EDIT_ALERT_LIMITS"))

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
        self.foot_label.set_limits(
            self.limit.get('min') if self.limit else None,
            self.limit.get('max') if self.limit else None,
            self._breached_bound(),
        )
        self.update_guidance()

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
