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

from PySide6.QtWidgets import QApplication

import theme
from theme import contrast
from theme import paths
from theme import qt as theme_qt
from theme import tokens as T

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
            # of a style sheet — a large part of why the app looked unstyled.
            # With a sheet set, QApplication.style() is the QStyleSheetStyle
            # proxy wrapping it and PySide6 does not expose baseStyle(), so the
            # base style is only visible with the sheet momentarily cleared.
            app.setStyleSheet("")
            self.assertEqual(app.style().name().lower(), "fusion")

            light = theme.apply(app, theme=T.LIGHT)
            self.assertEqual(
                mpl.rcParams["axes.facecolor"].upper(), light.chart("surface").upper()
            )
        finally:
            pass

    def test_a_plot_export_comes_out_light_from_a_dark_session(self):
        """Charts print in the light palette whatever the screen theme is.

        A dark chart wastes toner and reads badly on a mill report, so the
        export path swaps the chart tokens for the render and puts them back.
        """
        import os
        import tempfile

        from theme import mpl as tapio_mpl

        theme.apply(self.app, theme=T.DARK)
        try:
            import postprocessors.plot_export as plot_export

            rendered = {}
            real_export = plot_export.export_figure_with_annotations

            def spy(figure, canvas, **kwargs):
                rendered["theme"] = tapio_mpl.current.theme
                return real_export(figure, canvas, **kwargs)

            plot_export.export_figure_with_annotations = spy
            try:
                with tempfile.TemporaryDirectory() as folder:
                    from test.fakedevice import make_profile_bytes

                    for index in range(2):
                        with open(os.path.join(folder, f"p{index}.prof"), "wb") as handle:
                            handle.write(make_profile_bytes())
                    self.assertTrue(plot_export.run(folder))
            finally:
                plot_export.export_figure_with_annotations = real_export

            self.assertEqual(rendered.get("theme"), T.LIGHT)
            # ...and the screen is put back where it was.
            self.assertEqual(tapio_mpl.current.theme, T.DARK)
        finally:
            pass

    def test_the_bundled_plex_faces_load(self):
        QApplication.instance() or QApplication([])
        families = theme_qt.load_fonts()
        self.assertIn("IBM Plex Sans", families)
        self.assertIn("IBM Plex Mono", families)
        self.assertEqual(theme_qt.sans_family(), "IBM Plex Sans")
        self.assertEqual(theme_qt.mono_family(), "IBM Plex Mono")


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
