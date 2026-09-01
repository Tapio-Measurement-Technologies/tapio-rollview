"""The design system's own tests.

The contrast audit is the important one and it belongs in CI: if a token changes
and a pair drops below its threshold, the build should say so rather than a
person noticing months later on a mill floor. It runs in well under a second.

The rest guard the rules that are easy to break by accident — red leaking into
the categorical palette, a hand-written hex appearing in the tree, the style
sheet losing a placeholder.
"""

import pathlib
import re
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGridLayout,
    QLabel,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)

import theme
from theme import contrast
from theme import paths
from theme import qt as theme_qt
from theme import tokens as T
from test.qtcleanup import destroy

SRC = pathlib.Path(__file__).resolve().parents[1]


class TestContrast(unittest.TestCase):
    def test_every_pair_clears_its_threshold_in_both_themes(self):
        passes, failures = contrast.audit()
        self.assertEqual(failures, [], contrast.report())
        self.assertGreater(passes, 0)

    def test_ratio_is_symmetric_and_bounded(self):
        white, black = "#FFFFFF", "#000000"
        self.assertAlmostEqual(contrast.ratio(white, black), 21.0, places=2)
        self.assertAlmostEqual(
            contrast.ratio(white, black), contrast.ratio(black, white), places=9
        )
        self.assertAlmostEqual(contrast.ratio(white, white), 1.0, places=9)


class TestPalette(unittest.TestCase):
    """Red is a status colour, and only a status colour."""

    def test_red_is_absent_from_the_categorical_slots(self):
        red_ramp = {value.upper() for value in T.load().ramps["red"]}
        for name in T.THEMES:
            tokens = T.load(theme=name)
            overlap = red_ramp & {value.upper() for value in tokens.series}
            self.assertEqual(overlap, set(), f"{name}: red in the series palette")

    def test_the_diverging_scale_runs_blue_to_gold(self):
        # Never blue-to-red: a negative correlation is not an alarm, and
        # borrowing red would weaken the one signal that matters.
        red_ramp = {value.upper() for value in T.load().ramps["red"]}
        for name in T.THEMES:
            scale = {value.upper() for value in T.load(theme=name).diverging}
            self.assertEqual(scale & red_ramp, set(), f"{name}: red in the diverging scale")

    def test_the_recency_ramp_never_collides_with_the_mean(self):
        # A stacked profile must not be mistakeable for the mean drawn over it.
        for name in T.THEMES:
            tokens = T.load(theme=name)
            self.assertNotIn(tokens.color("accent").upper(),
                             [value.upper() for value in tokens.recency])

    def test_series_slots_are_never_cycled(self):
        tokens = T.load()
        slots = tokens.series
        self.assertEqual(tokens.series_color(0), slots[0])
        # A ninth series does not get a ninth colour.
        self.assertEqual(tokens.series_color(99), slots[-1])

    # A known collision inherited from the published guide, kept here rather
    # than quietly patched: in the dark theme the guide gives status `good` and
    # categorical slot 2 the same hex, #47A85B, even though it states that the
    # four status colours are "deliberately distinct from the eight categorical
    # hues so a status colour never impersonates a channel". In the light theme
    # they differ (#137D41 vs #3B9D51). Resolving it means changing one of the
    # two dark values in tokens.json — a design-system decision, not a
    # RollView one. Listing it explicitly means any *new* collision still fails.
    KNOWN_STATUS_SERIES_COLLISIONS = {(T.DARK, T.STATUS_GOOD, "#47A85B")}

    def test_status_colours_are_distinct_from_every_series_slot(self):
        found = set()
        for name in T.THEMES:
            tokens = T.load(theme=name)
            series = {value.upper() for value in tokens.series}
            for state in (T.STATUS_GOOD, T.STATUS_WARN, T.STATUS_BAD, T.STATUS_IDLE):
                color = tokens.status_color(state).upper()
                if color in series:
                    found.add((name, state, color))
        self.assertEqual(
            found, self.KNOWN_STATUS_SERIES_COLLISIONS,
            "a status colour impersonates a chart channel",
        )


class TestTokenTable(unittest.TestCase):
    def test_both_themes_define_the_same_roles(self):
        light = T.load(theme=T.LIGHT)._semantic
        dark = T.load(theme=T.DARK)._semantic
        self.assertEqual(set(light), set(dark))

    def test_an_unknown_role_is_an_error_not_a_default(self):
        with self.assertRaises(KeyError):
            T.load().color("brand-ish-blue")

    def test_there_is_one_layout(self):
        """RollView ships a single set of metrics, not a density scale.

        The system defines four densities so one token set can serve a desktop,
        a tablet and a handheld. RollView is the desktop and only the desktop,
        so it carries that one row — see the note in tokens.json for what a
        touch build would raise them to.
        """
        metrics = T.load().metrics
        self.assertEqual(
            set(metrics), {"row", "control", "min_target", "text"}
        )
        self.assertEqual(metrics["row"], 28)
        self.assertEqual(metrics["text"], 13)


class ThemeRestoringTestCase(unittest.TestCase):
    """Puts the application theme back the way it was found.

    These tests apply themes as their subject matter, and a theme reaches the
    metrics every later test measures. What was current before is restored,
    rather than a guess at what the default is.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._restore = theme_qt.tokens().theme

    def tearDown(self):
        theme.apply(self.app, theme=self._restore)


class TestStylesheet(ThemeRestoringTestCase):
    """The QSS is generated. A hand-edited hex in it is a bug, not a setting."""

    def test_the_template_contains_no_literal_colours(self):
        template = (SRC / "theme" / "rollview.qss").read_text(encoding="utf-8")
        # One exception, stated where it appears: white on the alarm band, which
        # is white because the band is always the same red in both themes.
        hexes = [h for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", template)
                 if h.upper() != "#FFFFFF"]
        self.assertEqual(hexes, [], f"literal colours in rollview.qss: {hexes}")

    def test_every_placeholder_resolves(self):
        for name in T.THEMES:
            theme_qt.apply(self.app, theme=name)
            sheet = self.app.styleSheet()
            self.assertNotIn("${", sheet)
            self.assertGreater(len(sheet), 1000)

    def test_the_stylesheet_never_kills_an_outline(self):  # noqa: D401
        # "No `outline: none` anywhere, in any toolkit, ever" applies to focus
        # indicators. Item views set it to drop Qt's dotted current-item marker,
        # which is not the focus ring — every focusable control below has an
        # explicit 2 px border in the focus colour instead.
        theme_qt.apply(self.app, theme=T.LIGHT)
        sheet = self.app.styleSheet()
        self.assertIn("border: 2px solid", sheet)


class TestApply(ThemeRestoringTestCase):
    def test_apply_swaps_both_the_widgets_and_the_charts(self):
        import matplotlib as mpl

        app = self.app
        try:
            dark = theme.apply(app, theme=T.DARK)
            self.assertEqual(dark.theme, T.DARK)
            self.assertEqual(
                mpl.rcParams["axes.facecolor"].upper(), dark.chart("surface").upper()
            )
            # Fusion, because the native Windows style silently ignores much
            # of a style sheet — a large part of why the app looked unstyled —
            # behind RollViewStyle, which corrects the few behaviours a style
            # sheet cannot reach. With a sheet set, QApplication.style() is the
            # QStyleSheetStyle proxy wrapping that and PySide6 does not expose
            # its baseStyle(), so both are only visible with the sheet
            # momentarily cleared.
            app.setStyleSheet("")
            self.assertIsInstance(app.style(), theme_qt.RollViewStyle)
            self.assertEqual(app.style().baseStyle().name().lower(), "fusion")

            light = theme.apply(app, theme=T.LIGHT)
            self.assertEqual(
                mpl.rcParams["axes.facecolor"].upper(), light.chart("surface").upper()
            )
        finally:
            pass

    def test_chart_type_is_the_token_scale_in_pixels(self):
        """The charts are typed on the same scale as the interface around them.

        Matplotlib measures type in points against the figure's dpi while the
        token scale is in CSS pixels, so a step handed over unconverted renders
        39 % larger — which is what made the axis labels read bigger than every
        Qt label on the tab.
        """
        import matplotlib as mpl

        from theme import mpl as tapio_mpl

        tokens = theme.apply(self.app, theme=T.LIGHT)
        for rc_param, step in (
            ("axes.labelsize", "body-sm"),
            ("axes.titlesize", "body"),
            ("xtick.labelsize", "eyebrow"),
            ("ytick.labelsize", "eyebrow"),
            ("font.size", "body-sm"),
        ):
            with self.subTest(rc_param=rc_param):
                self.assertAlmostEqual(
                    mpl.rcParams[rc_param] * tapio_mpl.FIGURE_DPI / 72.0,
                    tokens.font_size(step),
                    places=6,
                )

        # A label outranks the ticks it labels, in the charts as in the sheet.
        self.assertGreater(mpl.rcParams["axes.labelsize"], mpl.rcParams["xtick.labelsize"])

    def test_a_plot_export_comes_out_light_from_a_dark_session(self):
        """Charts print in the light palette whatever the screen theme is.

        A dark chart wastes toner and reads badly on a mill report. What is
        asserted here is not only that the render came out light, but that the
        *global* chart tokens never moved while it did: postprocessors run on a
        worker thread, and the GUI thread reads those globals whenever it draws.
        """
        import os
        import tempfile

        from matplotlib.colors import to_hex

        from theme import mpl as tapio_mpl

        try:
            from test.fakedevice import make_profile_bytes
        except ImportError:  # no pseudo-terminal on this platform
            self.skipTest("the profile fixture lives with the fake RQFT device")

        light = T.load(theme=T.LIGHT)
        import postprocessors.plot_export as plot_export

        # The written PNG, not the Figure object. savefig takes its background
        # from rcParams['savefig.facecolor'] rather than from the figure, so a
        # figure can be light and the file it writes still dark; asserting on
        # the figure alone would miss exactly that.
        with tempfile.TemporaryDirectory() as parent:
            # The same folder name both times — the chart is titled with it, so
            # two temp directories would differ for a reason that is not colour.
            folder = os.path.join(parent, "250520-134139")
            os.makedirs(folder)
            for index in range(2):
                with open(os.path.join(folder, f"p{index}.prof"), "wb") as handle:
                    handle.write(make_profile_bytes())
            written = os.path.join(folder, "250520-134139.png")

            rendered = {}
            real_export = plot_export.export_figure_with_annotations

            def spy(figure, canvas, **kwargs):
                # The screen's own tokens, sampled mid-render.
                rendered["global_theme"] = tapio_mpl.current.theme
                rendered["face"] = to_hex(figure.get_facecolor()).upper()
                return real_export(figure, canvas, **kwargs)

            exports = {}
            plot_export.export_figure_with_annotations = spy
            try:
                for name in (T.DARK, T.LIGHT):
                    theme.apply(self.app, theme=name)
                    self.assertTrue(plot_export.run(folder))
                    with open(written, "rb") as handle:
                        exports[name] = handle.read()
                    if name == T.DARK:
                        # Neither the render nor anything after it moved the
                        # application's chart tokens: postprocessors run on a
                        # worker thread and the GUI thread reads those globals.
                        self.assertEqual(rendered["global_theme"], T.DARK)
                        self.assertEqual(tapio_mpl.current.theme, T.DARK)
                        self.assertEqual(
                            rendered["face"], light.color("surface").upper()
                        )
            finally:
                plot_export.export_figure_with_annotations = real_export

            self.assertEqual(
                exports[T.DARK], exports[T.LIGHT],
                "the exported plot depends on the screen theme",
            )

    def test_the_bundled_plex_faces_load(self):
        QApplication.instance() or QApplication([])
        families = theme_qt.load_fonts()
        self.assertIn("IBM Plex Sans", families)
        self.assertIn("IBM Plex Mono", families)
        self.assertEqual(theme_qt.sans_family(), "IBM Plex Sans")
        self.assertEqual(theme_qt.mono_family(), "IBM Plex Mono")


class TestStateReachesTheChildren(ThemeRestoringTestCase):
    """A state set on a container has to restyle what is inside it.

    The sheet keys colour off ancestors — ``QWidget#statTile[state="bad"] QLabel``
    is what takes a failing tile's eyebrow and unit red along with its number —
    and Qt caches each widget's resolved rules until that widget is repolished.
    Repolishing the container alone left the labels inside it painted for the
    state before, which is how a tile over its alert limit came up half red and
    corrected itself only at the next theme change.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_a_container_state_recolours_the_labels_inside_it(self):
        tile = QWidget()
        tile.setObjectName("statTile")
        layout = QVBoxLayout(tile)
        label = QLabel("MEAN", tile)
        theme_qt.set_role(label, "eyebrow")
        layout.addWidget(label)
        self.addCleanup(destroy, tile)

        tile.show()
        muted = theme_qt.tokens().color("ink-muted").upper()
        self.assertEqual(
            label.palette().color(QPalette.ColorRole.WindowText).name().upper(), muted
        )

        theme_qt.set_state(tile, theme.STATUS_BAD)
        self.assertEqual(
            label.palette().color(QPalette.ColorRole.WindowText).name().upper(),
            theme_qt.tokens().color("bad").upper(),
        )

        theme_qt.set_state(tile, None)
        self.assertEqual(
            label.palette().color(QPalette.ColorRole.WindowText).name().upper(), muted
        )


class TestAlertLimitEditorStyling(ThemeRestoringTestCase):
    """A dialog opened from a failing tile is not itself an alarm.

    The sheet paints a failing tile's labels red through an ancestor selector,
    and Qt resolves those selectors down the parent chain — through a dialog
    parented to the tile as readily as through the tile's own layout. That put
    "Lower" and "Upper" in alarm red in a dialog whose job is to edit a number.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_the_editor_does_not_inherit_the_tiles_alarm(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog
        from gui.widgets.AlertLimitEditor import AlertLimitEditor
        from gui.widgets.stats import MaxWidget

        window = QWidget()
        layout = QVBoxLayout(window)
        tile = MaxWidget([1.0, 2.0], limit={'name': 'max_g', 'min': None, 'max': 0.5})
        layout.addWidget(tile)
        self.addCleanup(destroy, window)
        window.show()

        self.assertEqual(tile.property("state"), theme.STATUS_BAD)

        opened = []

        def capture(dialog):
            opened.append(dialog)
            return QDialog.DialogCode.Rejected

        with patch.object(AlertLimitEditor, "exec", capture):
            tile.open_alert_limit_editor()

        editor = opened[0]
        self.addCleanup(destroy, editor)
        editor.show()

        bad = theme_qt.tokens().color("bad").upper()
        field_labels = [
            label for label in editor.findChildren(QLabel)
            if label.text() and label is not editor.error_label
        ]
        self.assertTrue(field_labels)
        for label in field_labels:
            with self.subTest(label=label.text()):
                self.assertNotEqual(
                    label.palette().color(QPalette.ColorRole.WindowText).name().upper(),
                    bad,
                )

        # The one label that *is* an alarm keeps its colour, since it carries
        # the state itself rather than inheriting it.
        editor.error_label.show()
        self.assertEqual(
            editor.error_label.palette().color(QPalette.ColorRole.WindowText).name().upper(),
            bad,
        )

class TestStatTileFooter(ThemeRestoringTestCase):
    """The limit line is the first thing on a tile asked to give up width.

    Seven tiles across one row leave it about a dozen characters, and a bound
    that elides to "≤ 5…" states nothing at all, so it is set a step below the
    rest of the tile.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_the_limit_line_is_set_a_step_below_the_value(self):
        from gui.widgets.stats import MaxWidget

        tile = MaxWidget([1.0, 2.0], limit={'name': 'max_g', 'min': 1.0, 'max': 5.0})
        self.addCleanup(destroy, tile)
        tile.show()

        tokens = theme_qt.tokens()
        self.assertEqual(
            tile.foot_label.min_chunk.font().pixelSize(), tokens.font_size("eyebrow")
        )
        self.assertLess(
            tile.foot_label.min_chunk.font().pixelSize(),
            tile.value_label.font().pixelSize(),
        )

    def test_a_two_sided_limit_is_not_cut_short_at_a_row_width(self):
        """Seven tiles across a 900 px row is what the tiles actually get.

        Both bounds have to be readable there; a footer that elides at the
        width the row hands out is a footer that elides all the time.
        """
        from PySide6.QtWidgets import QLabel
        from gui.widgets.stats import MaxWidget

        tile = MaxWidget([1.0, 2.0], limit={'name': 'max_g', 'min': 10.0, 'max': 22.0})
        self.addCleanup(destroy, tile)
        tile.resize(128, tile.sizeHint().height())
        tile.show()
        tile.foot_label.adjustSize()

        for chunk in (tile.foot_label.min_chunk, tile.foot_label.max_chunk):
            # ElidedLabel keeps the full string; QLabel holds what is painted.
            self.assertEqual(QLabel.text(chunk), chunk.text())

    def test_the_breached_bound_is_not_elided_by_a_rounding_error(self):
        """A bold bound given the width it asked for still says all of itself.

        The chunk sizes itself with ``horizontalAdvance()`` and Qt elides with
        the text engine's own measure; on a 500-weight string the two differ by
        a pixel, which was enough to turn "≤ 40.0" into "≤ 40…" — a limit that
        reads as a different number.
        """
        from PySide6.QtWidgets import QLabel as _QLabel
        from gui.widgets.stats import MaxWidget

        tile = MaxWidget([1.0, 99.0], limit={'name': 'max_g', 'min': 10.0, 'max': 40.0})
        self.addCleanup(destroy, tile)
        tile.resize(150, tile.sizeHint().height())
        tile.show()

        chunk = tile.foot_label.max_chunk
        self.assertEqual(chunk.property("limit"), "breached")
        self.assertEqual(_QLabel.text(chunk), chunk.text())

    def test_a_font_change_re_elides_instead_of_clipping(self):
        """The elide is stale the moment the font moves under it.

        A theme switch sets the application font after the style sheet, and a
        tile repolished into its alarm state gives the breached bound a heavier
        weight. Neither changes the label's width, so no resize arrives to
        re-run the elide — and QLabel paints the too-long string by cutting the
        end off, with no ellipsis to say it did.
        """
        from PySide6.QtGui import QFont, QFontMetrics
        from PySide6.QtWidgets import QLabel as _QLabel
        from gui.widgets.stats import MaxWidget

        tile = MaxWidget([1.0, 99.0], limit={'name': 'max_g', 'min': 10.0, 'max': 40.0})
        self.addCleanup(destroy, tile)
        tile.resize(150, tile.sizeHint().height())
        tile.show()

        chunk = tile.foot_label.max_chunk
        chunk.setFixedWidth(chunk.width())  # the tile does not get any wider
        bigger = QFont(chunk.font())
        bigger.setPixelSize(bigger.pixelSize() + 4)
        chunk.setFont(bigger)

        painted = _QLabel.text(chunk)
        self.assertLessEqual(
            QFontMetrics(chunk.font()).horizontalAdvance(painted), chunk.width()
        )

    def test_a_padded_bound_is_measured_inside_its_own_box(self):
        """Padding from the sheet is width the text does not get.

        Qt reports a style sheet's padding as contents margins and QLabel paints
        the text inside them. A chunk that sizes and elides against its whole
        width therefore overruns a padded label by exactly the padding, and
        QLabel clips the overrun without an ellipsis — which is how a limit came
        to be drawn as "≤ 40" when it says "≤ 40.0".
        """
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QLabel as _QLabel
        from gui.widgets.stats import MaxWidget

        tile = MaxWidget([1.0, 99.0], limit={'name': 'max_g', 'min': 10.0, 'max': 40.0})
        self.addCleanup(destroy, tile)
        chunk = tile.foot_label.max_chunk
        chunk.setStyleSheet("QLabel { padding: 0 4px; }")
        tile.resize(150, tile.sizeHint().height())
        tile.show()
        tile.foot_label.adjustSize()

        self.assertEqual(chunk.box_width(), 8)
        self.assertGreaterEqual(chunk.sizeHint().width(), chunk.box_width())
        self.assertEqual(_QLabel.text(chunk), chunk.text())
        self.assertLessEqual(
            QFontMetrics(chunk.font()).horizontalAdvance(chunk.text()),
            chunk.contentsRect().width(),
        )


class TestComboBoxPopup(ThemeRestoringTestCase):
    """A drop-down opens below its field and scrolls like a list.

    Fusion answers ``SH_ComboBox_Popup`` with true for a non-editable combo,
    which opens the list *over* the control anchored on the current item, drops
    ``maxVisibleItems`` and reaches anything past the edge of the screen through
    two auto-scrolling arrow strips instead of a scrollbar — options that read as
    missing, and a list that lurches a row at a time.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_the_popup_is_a_drop_down_not_a_menu(self):
        combo = QComboBox()
        combo.addItems([f"Option {i}" for i in range(4)])
        self.addCleanup(destroy, combo)

        option = QStyleOptionComboBox()
        option.initFrom(combo)
        self.assertEqual(
            combo.style().styleHint(
                QStyle.StyleHint.SH_ComboBox_Popup, option, combo
            ),
            0,
        )

    def test_the_popup_scrolls_by_the_pixel(self):
        combo = QComboBox()
        combo.addItems([f"Option {i}" for i in range(40)])
        self.addCleanup(destroy, combo)
        combo.show()

        self.assertEqual(
            combo.view().verticalScrollMode(),
            QAbstractItemView.ScrollMode.ScrollPerPixel,
        )


class TestDensity(unittest.TestCase):
    """Spacing is the one part of the system a new screen can silently miss.

    Colour, type and the palette reach a widget through the application style
    sheet whether or not its author knows the system exists. Layout metrics
    cannot: Qt's defaults are 11 px margins and 6 px spacing, neither of which
    is on the 4 px grid, and no style sheet rule can reach them. So every
    layout in ``src/gui`` goes through ``theme_qt.pad`` / ``theme_qt.gap``, and
    this fails the build when one does not.
    """

    RAW_CALLS = re.compile(
        r"\.(setContentsMargins|setSpacing|setHorizontalSpacing|setVerticalSpacing)\("
    )

    def test_no_layout_sets_its_own_pixels(self):
        offenders = []
        for path in sorted((SRC / "gui").rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.RAW_CALLS.search(line):
                    offenders.append(f"{path.relative_to(SRC)}:{number}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            "layout metrics set in raw pixels; use theme_qt.pad() / theme_qt.gap()"
            " so the spacing stays on the token grid:\n" + "\n".join(offenders),
        )

    def test_pad_and_gap_resolve_to_the_scale(self):
        app = QApplication.instance() or QApplication([])
        theme.apply(app, theme=T.LIGHT)
        t = theme_qt.tokens()

        widget = QWidget()
        layout = QVBoxLayout(widget)

        theme_qt.pad(layout, 3)
        margins = layout.contentsMargins()
        self.assertEqual(
            [margins.left(), margins.top(), margins.right(), margins.bottom()],
            [t.space(3)] * 4,
        )

        # Two arguments are horizontal then vertical; four are Qt's own order.
        theme_qt.pad(layout, 2, 1)
        margins = layout.contentsMargins()
        self.assertEqual(
            [margins.left(), margins.top(), margins.right(), margins.bottom()],
            [t.space(2), t.space(1), t.space(2), t.space(1)],
        )

        theme_qt.pad(layout, 2, 1, 2, 3)
        margins = layout.contentsMargins()
        self.assertEqual(
            [margins.left(), margins.top(), margins.right(), margins.bottom()],
            [t.space(2), t.space(1), t.space(2), t.space(3)],
        )

        # 0 is no margin, not a step on the scale.
        theme_qt.pad(layout, 0)
        margins = layout.contentsMargins()
        self.assertEqual(
            [margins.left(), margins.top(), margins.right(), margins.bottom()],
            [0, 0, 0, 0],
        )

        theme_qt.gap(layout, 2)
        self.assertEqual(layout.spacing(), t.space(2))
        theme_qt.gap(layout, 0)
        self.assertEqual(layout.spacing(), 0)

        grid = QGridLayout()
        theme_qt.gap(grid, 1, 3)
        self.assertEqual(grid.horizontalSpacing(), t.space(1))
        self.assertEqual(grid.verticalSpacing(), t.space(3))

        destroy(widget)


class TestPackaging(unittest.TestCase):
    """The theme's data files have to survive PyInstaller.

    ``tokens.json`` and ``rollview.qss`` are data, not code, so PyInstaller does
    not pick them up by following imports — they only reach a bundle because
    ``build.yml`` lists them as ``--add-data``. Without them ``theme.qt`` fails
    at import, which takes the crash dialog down with it: the packaged app dies
    before it draws a window, and CI never sees it because CI runs from source.
    """

    BUILD_WORKFLOW = SRC.parent / ".github" / "workflows" / "build.yml"

    def _add_data_sources(self):
        text = self.BUILD_WORKFLOW.read_text(encoding="utf-8")
        return set(re.findall(r'--add-data "([^:"]+):', text))

    def test_every_theme_data_file_resolves(self):
        for name in ("tokens.json", "rollview.qss"):
            with self.subTest(name):
                self.assertTrue(pathlib.Path(paths.theme_file(name)).is_file())

    def test_every_theme_data_file_is_bundled(self):
        # Anything in the package that is not Python is a data file, so a new
        # one added later fails here rather than in the field.
        data_files = sorted(
            path for path in (SRC / "theme").iterdir()
            if path.is_file() and path.suffix != ".py"
        )
        self.assertTrue(data_files, "expected theme data files to exist")

        declared = self._add_data_sources()
        for path in data_files:
            with self.subTest(path.name):
                self.assertIn(
                    f"src/theme/{path.name}", declared,
                    f"{path.name} is not in build.yml's --add-data list, so it "
                    f"will be missing from the packaged application",
                )

    def test_the_plex_faces_are_bundled(self):
        font_dir = pathlib.Path(paths.asset_dir("fonts", "plex"))
        self.assertTrue(sorted(font_dir.glob("*.ttf")))
        # The fonts ride along on the whole-directory rule.
        self.assertIn("src/assets/fonts/", self._add_data_sources())


if __name__ == "__main__":
    unittest.main()


class TestSystemTheme(ThemeRestoringTestCase):
    """"System" is a preference, not a third token table.

    It resolves to one of the two at the moment a theme is applied, and what
    was asked for is remembered separately so a later change of desktop
    appearance can be followed.
    """

    def setUp(self):
        super().setUp()
        self._restore_requested = theme_qt.requested

    def tearDown(self):
        super().tearDown()
        theme.apply(self.app, theme=self._restore_requested)

    @staticmethod
    def _desktop(scheme):
        """Answer for the platform.

        setColorScheme() is not usable here: the offscreen platform ignores it
        and reports Unknown whatever it is told.
        """
        from unittest.mock import patch

        return patch.object(theme_qt, "desktop_scheme", lambda: scheme)

    def test_system_is_a_choice_but_not_a_table(self):
        self.assertIn(T.SYSTEM, T.CHOICES)
        self.assertNotIn(T.SYSTEM, T.THEMES)
        # Asked for a table it does not have, it falls back rather than raising.
        self.assertEqual(T.load(theme=T.SYSTEM).theme, T.LIGHT)

    def test_it_resolves_to_whichever_the_desktop_reports(self):
        with self._desktop(Qt.ColorScheme.Dark):
            self.assertEqual(theme_qt.resolve(T.SYSTEM), T.DARK)
        with self._desktop(Qt.ColorScheme.Light):
            self.assertEqual(theme_qt.resolve(T.SYSTEM), T.LIGHT)
        # A platform that reports nothing gets the product default, not a guess.
        with self._desktop(Qt.ColorScheme.Unknown):
            self.assertEqual(theme_qt.resolve(T.SYSTEM), T.LIGHT)

    def test_an_explicit_choice_ignores_the_desktop(self):
        with self._desktop(Qt.ColorScheme.Dark):
            self.assertEqual(theme_qt.resolve(T.LIGHT), T.LIGHT)
            self.assertEqual(theme_qt.resolve(T.DARK), T.DARK)

    def test_applying_system_keeps_the_choice_and_the_resolution_apart(self):
        with self._desktop(Qt.ColorScheme.Dark):
            resolved = theme.apply(self.app, theme=T.SYSTEM)

        # The tokens are a real table...
        self.assertEqual(resolved.theme, T.DARK)
        self.assertEqual(theme.current().theme, T.DARK)
        # ...and the charts moved with them, not to the word "system".
        from theme import mpl as tapio_mpl
        self.assertEqual(tapio_mpl.current.theme, T.DARK)
        # ...but what was asked for is still "system", which is what lets a
        # later desktop change be followed.
        self.assertEqual(theme.requested(), T.SYSTEM)


class TestApplicationFont(ThemeRestoringTestCase):
    """The application font has to be set after the style sheet.

    setStyleSheet() installs QStyleSheetStyle, and a style change re-seeds Qt's
    per-class widget font hash from the platform theme. Those entries —
    QMenuBar, QTreeView, QCheckBox, QMenu, QToolButton, QListView — outrank the
    plain application font, so a font set *before* the sheet is silently
    overruled for exactly those classes and they come up in the desktop's font
    at the desktop's size. Every later apply() then corrected them, which read
    as "changing the theme shrinks the interface".

    Asserted as an ordering rather than by measuring a widget, because the
    offscreen platform CI runs on supplies no per-class fonts at all: the bug is
    invisible there and a measuring test would pass while shipping it.
    """

    class _Recorder:
        """Stands in for the QApplication, and remembers the order of calls."""

        def __init__(self, real):
            self._real = real
            self.calls = []

        def __getattr__(self, name):
            return getattr(self._real, name)

        def setStyle(self, *a):
            self.calls.append("setStyle")

        def setPalette(self, *a):
            self.calls.append("setPalette")

        def setStyleSheet(self, *a):
            self.calls.append("setStyleSheet")

        def setFont(self, *a):
            self.calls.append("setFont")

    def test_the_font_is_asserted_after_the_style_sheet(self):
        recorder = self._Recorder(self.app)

        theme_qt.apply(recorder, theme=T.LIGHT)

        self.assertIn("setFont", recorder.calls)
        self.assertIn("setStyleSheet", recorder.calls)
        self.assertGreater(
            recorder.calls.index("setFont"), recorder.calls.index("setStyleSheet"),
            "the style sheet re-seeds Qt's per-class font hash, so a font set "
            "before it is overruled for QMenuBar, QTreeView, QCheckBox and the "
            f"rest — order was {recorder.calls}",
        )

    def test_the_base_font_is_the_token_size_in_pixels(self):
        theme.apply(self.app, theme=T.LIGHT)
        base = self.app.font()
        self.assertEqual(base.pixelSize(), theme_qt.tokens().base_text_size)
        # Points, not pixels, would be a third too large at 96 dpi and out of
        # step with every size in the style sheet.
        self.assertEqual(base.pointSize(), -1)
        self.assertEqual(base.family(), theme_qt.sans_family())


class TestLiveDensity(unittest.TestCase):
    """Every layout in the live window sits on the 4 px grid.

    The source lint in TestDensity catches a raw ``setContentsMargins`` call.
    It cannot catch the *absence* of one: a layout nobody spaces keeps Qt's own
    defaults — 9 px margins and 6 px spacing, neither on the grid — and so does
    every layout Qt builds for its own composite widgets, the page stack inside
    a QTabWidget, the box inside a QStatusBar, QMainWindow's own. Fourteen of
    them were off-grid with the source lint entirely green.

    This walks the assembled tree instead, so it does not care how a layout came
    to exist or who wrote it.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_layout_is_off_the_grid(self):
        from unittest.mock import patch

        from gui.main_window import MainWindow
        from gui.settings import SettingsWindow

        theme.apply(self.app, theme=T.LIGHT)
        tokens = theme_qt.tokens()
        grid = {0} | {tokens.space(step) for step in (1, 2, 3, 4, 6, 8, 12)}

        with patch("gui.main_window.SerialWidget.scan_devices"):
            window = MainWindow()
        settings_window = SettingsWindow()
        try:
            offenders = []
            for root in (window, settings_window):
                for child in root.findChildren(QWidget) + [root]:
                    # `layout` is shadowed by an attribute on a few widgets.
                    layout = QWidget.layout(child)
                    if layout is None:
                        continue
                    margins = layout.contentsMargins()
                    values = {
                        "left": margins.left(), "top": margins.top(),
                        "right": margins.right(), "bottom": margins.bottom(),
                        "spacing": layout.spacing(),
                    }
                    off = {k: v for k, v in values.items() if v not in grid}
                    if off:
                        offenders.append(
                            f"{child.__class__.__name__}."
                            f"{layout.__class__.__name__}: {off}"
                        )
            self.assertEqual(
                sorted(set(offenders)), [],
                "layouts off the 4 px grid — theme_qt.pad()/gap() them, "
                "including the ones Qt built for you:\n  "
                + "\n  ".join(sorted(set(offenders))),
            )
        finally:
            destroy(settings_window)
            destroy(window)
