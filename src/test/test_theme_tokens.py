"""The design system's own tests.

The contrast audit is the important one and it belongs in CI: if a token changes
and a pair drops below its threshold, the build should say so rather than a
person noticing months later on a mill floor. It runs in well under a second.

The rest guard the rules that are easy to break by accident — red leaking into
the categorical palette, a hand-written hex appearing in the tree, the style
sheet losing a placeholder.

Three of them guard something else: that RollView is still *consuming* the
system rather than carrying a copy of it that has quietly moved. The vendored
token file has to match the hash recorded beside it, RollView's own token file
may only ever add to it, and the role names have to be the system's own. Those
are cheap, they need no design-system checkout, and they are what the previous
arrangement had no way to check at all.
"""

import hashlib
import pathlib
import re
import unittest

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QListWidget,
    QMenu,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
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
        red_ramp = {value.upper() for value in T.load().ramp_steps("red")}
        for name in T.THEMES:
            tokens = T.load(theme=name)
            overlap = red_ramp & {value.upper() for value in tokens.series}
            self.assertEqual(overlap, set(), f"{name}: red in the series palette")

    def test_the_diverging_scale_runs_blue_to_gold(self):
        # Never blue-to-red: a negative correlation is not an alarm, and
        # borrowing red would weaken the one signal that matters.
        red_ramp = {value.upper() for value in T.load().ramp_steps("red")}
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


class TestVendoredTokens(unittest.TestCase):
    """The token file is the design system's, not a restructured copy of it.

    RollView used to carry its own arrangement of the same values: a different
    schema, a different set of role names, a version string of its own. Nothing
    compared the two, so a value that moved upstream never arrived and nothing
    anywhere reported that. What replaced it is a verbatim copy plus an
    additions-only overlay, which makes the comparison a diff and the drift a
    test failure.
    """

    def _vendored_digest(self):
        return hashlib.sha256(
            pathlib.Path(paths.theme_file("tapio-tokens.json")).read_bytes()
        ).hexdigest()

    def test_the_copy_is_the_hash_the_overlay_records(self):
        """Nobody edits the vendored file in place.

        This is the half of the check that needs no design-system checkout, so
        it runs everywhere: on any machine, in CI, in a packaged build's source
        tree. The other half — comparing against the system itself — is
        `scripts/sync_design_system.py --check`, run deliberately by whoever
        has the system to hand.
        """
        self.assertEqual(T.upstream()["sha256"], self._vendored_digest())

    def test_the_version_is_read_and_not_restated(self):
        self.assertEqual(theme.VERSION, T.upstream()["version"])
        self.assertEqual(T.load().version, T.upstream()["version"])

    def test_the_overlay_only_ever_adds(self):
        """RollView's file may add to the system's. It may not disagree with it.

        A key that appears in both is the beginning of a fork: two files that
        both claim to say what a value is, and nothing to say which of them is
        right. The overlay's job is the things the system genuinely does not
        author — a font fallback chain, which density row this application runs
        — and this is what holds it to that.
        """
        system = set(T.system_document())
        overlay = {
            key for key in T.rollview_document() if not key.startswith("$")
        }
        for key in sorted(overlay & system):
            with self.subTest(key):
                system_block = T.system_document()[key]
                overlay_block = T.rollview_document()[key]
                if not isinstance(system_block, dict):
                    self.fail(f"the overlay restates {key}, which the system authors")
                clash = {
                    name for name in overlay_block
                    if not name.startswith("$") and name in system_block
                }
                self.assertEqual(
                    clash, set(),
                    f"the overlay restates {key}.{'/'.join(sorted(clash))}, "
                    f"which the system already authors",
                )


class TestTokenTable(unittest.TestCase):
    def test_both_themes_define_the_same_roles(self):
        light = T.load(theme=T.LIGHT)._semantic
        dark = T.load(theme=T.DARK)._semantic
        self.assertEqual(set(light), set(dark))

    def test_the_roles_are_the_systems_roles(self):
        """One role, one name — the name the system and the guide use.

        RollView used to rename them on the way in: `danger` became `bad`,
        `surface-sunken` became `sunken`, `ink-link` became `link`. The values
        agreed, so nothing looked wrong, but a rule written in the guide's
        vocabulary had to be translated before it could be applied, and the
        system's own tooling could not be pointed at RollView's file at all.
        """
        authored = set(T.system_document()["semantic"][T.LIGHT])
        self.assertEqual(set(T.load().roles), authored)
        # The names that were renamed in the fork, spelled the system's way.
        for role in (
            "surface-sunken", "surface-raised", "surface-inverse", "ink-link",
            "border-focus", "warning", "warning-mark", "danger", "danger-mark",
            "ghost-bg", "ghost-ink",
        ):
            with self.subTest(role):
                self.assertTrue(T.load().color(role).startswith("#"))

    def test_a_state_is_painted_out_of_roles(self):
        """The four component states are not a fifth vocabulary of colour.

        `good`/`warn`/`bad`/`idle` are what a widget *is* — the guide's own QSS
        spells them that way — and each one resolves to roles the system
        authors. `good` has no separate mark token: in spec is one colour, which
        is what the guide's status row and the CSS export both say.
        """
        t = T.load()
        self.assertEqual(t.status_ink(T.STATUS_BAD), t.color("danger"))
        self.assertEqual(t.status_mark(T.STATUS_BAD), t.color("danger-mark"))
        self.assertEqual(t.status_ink(T.STATUS_WARN), t.color("warning"))
        self.assertEqual(t.status_mark(T.STATUS_WARN), t.color("warning-mark"))
        self.assertEqual(t.status_mark(T.STATUS_GOOD), t.color("good"))
        self.assertEqual(t.status_ink(T.STATUS_IDLE), t.color("ink-muted"))

    def test_an_unknown_role_is_an_error_not_a_default(self):
        with self.assertRaises(KeyError):
            T.load().color("brand-ish-blue")

    def test_the_density_scale_is_carried_whole(self):
        """"Same system, different density" is one of the six principles.

        The scale exists so that one token set serves a lab desktop, a
        mill-floor tablet and a handheld: only the row height, the control
        height, the hit target and the base text size change between them.
        RollView used to flatten it to the one row it runs at, which meant a
        touch build was a re-measurement rather than a parameter, and a second
        application copying RollView's tokens would have inherited a system with
        the principle taken out of it.
        """
        rows = T.load().densities
        self.assertEqual(set(rows), set(T.DENSITIES))
        for name, expected in {
            # The guide's density table, which is also the CSS and Qt exports'.
            T.COMPACT: (28, 28, 32, 13),
            T.COMFORTABLE: (36, 36, 32, 15),
            T.FIELD: (56, 48, 48, 17),
        }.items():
            with self.subTest(name):
                row = rows[name]
                self.assertEqual(
                    (row["row"], row["control"], row["min_target"], row["text"]),
                    expected,
                )

    def test_rollview_runs_the_desktop_row(self):
        t = T.load()
        self.assertEqual(t.density, T.COMPACT)
        self.assertEqual((t.row_height, t.control_height), (28, 28))
        self.assertEqual((t.min_target, t.base_text_size), (32, 13))

    def test_a_density_survives_a_theme_change(self):
        """A night-shift toggle re-applies the theme, not the whole preference.

        Without this a field build would drop back to desktop rows the first
        time the operator switched to dark.
        """
        app = QApplication.instance() or QApplication([])
        was = theme_qt.tokens()
        try:
            field = theme.apply(app, theme=T.LIGHT, density=T.FIELD)
            self.assertEqual(field.density, T.FIELD)
            self.assertEqual(theme.apply(app, theme=T.DARK).density, T.FIELD)
        finally:
            theme.apply(app, theme=was.theme, density=was.density)

    def test_a_density_is_one_argument(self):
        """The point of the scale is that changing it is a parameter."""
        field = T.load(density=T.FIELD)
        self.assertEqual(field.row_height, 56)
        self.assertEqual(field.min_target, field.target("touch"))
        # ...and an unknown one falls back rather than raising in front of an
        # operator: a bad preference should not take the window down.
        self.assertEqual(T.load(density="enormous").density, T.COMPACT)


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

    def test_every_variant_is_named_in_the_disabled_rule(self):
        """`:disabled` and `[variant="..."]` tie, so the later rule wins.

        `QPushButton:disabled` on its own therefore loses to
        `QPushButton[variant="primary"]` declared below it, and a disabled
        primary keeps its blue fill, its white label and its accent border —
        pixel for pixel an enabled button that does not respond. Naming the
        variant breaks the tie. The sheet generates the list from
        `theme.qt.VARIANTS` so a variant added there cannot be left out of it.
        """
        theme_qt.apply(self.app, theme=T.LIGHT)
        sheet = self.app.styleSheet()
        for variant in theme_qt.VARIANTS:
            with self.subTest(variant):
                self.assertIn(f'QPushButton[variant="{variant}"]:disabled', sheet)

    def test_the_stylesheet_never_kills_an_outline(self):  # noqa: D401
        # "No `outline: none` anywhere, in any toolkit, ever" applies to focus
        # indicators. Item views set it to drop Qt's dotted current-item marker,
        # which is not the focus ring — every focusable control below has an
        # explicit 2 px border in the focus colour instead.
        theme_qt.apply(self.app, theme=T.LIGHT)
        sheet = self.app.styleSheet()
        self.assertIn("border: 2px solid", sheet)


class TestChartChrome(unittest.TestCase):
    """The chart chrome is the system's, whole.

    RollView used to carry a shortened version of it: the axis-label and title
    inks dropped, and the limit band re-expressed as a separate colour and an
    alpha. Nothing looked wrong — the interface's own `ink-muted` is close to
    the chrome's `label` — but the two files could not be compared even for the
    values they shared, which is the whole point of having one of them.
    """

    def test_the_chrome_roles_are_the_systems(self):
        authored = set(
            T.system_document()["chart"]["chrome"][T.LIGHT]
        )
        t = T.load()
        for role in authored:
            with self.subTest(role):
                self.assertTrue(t.chart(role))
        # The two that were dropped, and are the reason axis labels were being
        # drawn in an interface ink rather than a chart one.
        for role in ("label", "title"):
            self.assertIn(role, authored)
            self.assertNotEqual(t.chart(role), t.color("ink-muted"))

    def test_the_limit_band_is_one_token(self):
        """One CSS colour with its alpha in it, as the system authors it."""
        for name in T.THEMES:
            with self.subTest(name):
                t = T.load(theme=name)
                authored = T.system_document()["chart"]["chrome"][name]["limit-band"]
                color, alpha = t.limit_band
                self.assertEqual(
                    (color, alpha), T.parse_rgba(authored)
                )
                # ...and it is the limit's own hue, not a second red.
                self.assertEqual(color.upper(), t.chart("limit").upper())

    def test_marks_are_the_systems_points_and_export_is_thinner(self):
        """Mark sizes are in points, not pixels.

        The same "2 px" line is a different physical thickness on a HiDPI
        laptop, in a screenshot, in a 300 dpi print and in a PDF. The system
        authors two columns — screen and export — and RollView used to carry
        neither, only a set of constants of its own.
        """
        screen = T.load(preset=T.SCREEN)
        export = T.load(preset=T.EXPORT)
        authored = T.system_document()["chart"]["mark"]
        self.assertEqual(authored["unit"], "pt")
        for name in ("series", "outOfSpec", "limit", "target", "axis", "grid"):
            with self.subTest(name):
                self.assertEqual(screen.mark(name), authored["screen"][name])
                self.assertLess(export.mark(name), screen.mark(name))
        # A profile behind the mean is thinner than the mean and never as heavy
        # as a limit line, which is not a data line at all.
        self.assertLess(screen.supporting_mark, screen.mark("series"))
        self.assertLess(screen.supporting_mark, screen.mark("limit"))

    def test_a_raster_export_is_never_below_300_dpi(self):
        self.assertGreaterEqual(T.load().raster_min_dpi, 300)
        self.assertEqual(T.load().vector_formats, ["pdf", "svg"])


class TestSpectrumRules(unittest.TestCase):
    """A spectrum is a quantitative estimate with units, not a picture."""

    def _axes(self):
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        return Figure().add_subplot(111)

    def test_it_refuses_to_draw_without_a_named_ordinate(self):
        """"Intensity" is not a quantity, and neither is a blank axis.

        What a peak height means depends entirely on what the ordinate is, so
        the ordinate is not optional.
        """
        from theme import mpl as tapio_mpl

        for quantity, unit in (("", "µm"), ("RMS amplitude", "")):
            with self.subTest(quantity=quantity, unit=unit):
                with self.assertRaises(ValueError):
                    tapio_mpl.spectrum(
                        self._axes(), [1, 2, 3], [1, 2, 3],
                        quantity=quantity, unit=unit,
                    )

    def test_frequency_is_the_coordinate_and_the_axis_is_logarithmic(self):
        from theme import mpl as tapio_mpl

        ax = self._axes()
        tapio_mpl.spectrum(ax, [0, 1, 10, 100], [0, 1, 2, 1],
                           quantity="RMS amplitude", unit="g")
        self.assertEqual(ax.get_xscale(), "log")
        # The zero-frequency bin carries the mean level, which is not a spatial
        # frequency and has nowhere to sit on a log axis.
        self.assertNotIn(0.0, ax.lines[0].get_xdata())

    def test_wavelength_is_a_second_scale_and_not_a_relabelling(self):
        """The one thing the system says never to do.

        Rewriting the frequency axis's ticks as λ = 1/f leaves the ordinate
        describing a quantity those ticks are not for: a density has to be
        transformed with the Jacobian, S_λ(λ) = S_f(1/λ)/λ². RollView used to
        offer exactly that as a setting.
        """
        from theme import mpl as tapio_mpl

        ax = self._axes()
        tapio_mpl.spectrum(ax, [1, 10, 100], [1, 2, 1],
                           quantity="RMS amplitude", unit="g")
        ax.set_xlabel("Spatial frequency [1/m]")
        top = tapio_mpl.wavelength_axis(ax)

        self.assertIsNot(top, ax)
        self.assertIn("frequency", ax.get_xlabel().lower())
        self.assertIn("wavelength", top.get_xlabel().lower())
        # 1/m in, mm out: 2 1/m is a 500 mm wavelength.
        forward = top._functions[0]
        self.assertAlmostEqual(float(forward(np.asarray(2.0))), 500.0)

    def test_the_line_is_not_filled(self):
        """Area under a spectrum has a meaning, and it is not being shown."""
        from theme import mpl as tapio_mpl

        ax = self._axes()
        tapio_mpl.spectrum(ax, [1, 10, 100], [1, 2, 1],
                           quantity="RMS amplitude", unit="g")
        self.assertEqual(list(ax.collections), [])
        self.assertEqual(len(ax.lines), 1)


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


class TestButtonVariants(ThemeRestoringTestCase):
    """Five variants, and every one of them can be told it is disabled.

    Rendered rather than read off the sheet: what matters is the pixels a
    disabled control puts on the screen, and the failure this guards against
    produced a perfectly valid style sheet that painted a disabled primary
    exactly like an enabled one.
    """

    def _render(self, variant, enabled):
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QPushButton

        button = QPushButton("Start measurement")
        theme_qt.set_variant(button, variant)
        button.setEnabled(enabled)
        button.resize(180, 32)
        pixmap = QPixmap(button.size())
        button.render(pixmap)
        image = pixmap.toImage()
        destroy(button)
        return image

    def test_a_disabled_button_never_looks_enabled(self):
        for name in T.THEMES:
            theme.apply(self.app, theme=name)
            for variant in theme_qt.VARIANTS:
                with self.subTest(theme=name, variant=variant):
                    self.assertNotEqual(
                        self._render(variant, enabled=True),
                        self._render(variant, enabled=False),
                        f"a disabled {variant} button is pixel for pixel an "
                        f"enabled one — nothing on it says it will not respond",
                    )

    def test_the_disabled_look_is_the_same_whatever_the_variant(self):
        """One disabled look, not five.

        A greyed-out control is not five different kinds of greyed out, and the
        contrast audit only checks the one pairing — `ink-muted` on the sunken
        ground — so five would leave four unchecked.
        """
        theme.apply(self.app, theme=T.LIGHT)
        rendered = [self._render(variant, enabled=False)
                    for variant in theme_qt.VARIANTS]
        for image in rendered[1:]:
            self.assertEqual(image, rendered[0])

    def test_a_variant_the_system_does_not_have_is_refused(self):
        from PySide6.QtWidgets import QPushButton

        button = QPushButton()
        with self.assertRaises(ValueError):
            theme_qt.set_variant(button, "subtle")
        destroy(button)

    def test_ghost_carries_a_fill_and_bare_does_not(self):
        """A control must look like a control without being hovered.

        v1.1 of the system split the old borderless ghost in two: ghost keeps a
        soft tinted fill so it still reads as a control on a screen nobody is
        hovering — a mill-floor tablet has no pointer at all — and `bare` is the
        truly borderless one, for icon actions inside a grouped toolbar.
        """
        from PySide6.QtGui import QColor

        for name in T.THEMES:
            theme.apply(self.app, theme=name)
            t = theme_qt.tokens()
            with self.subTest(name):
                ghost = self._render("ghost", enabled=True)
                # The top-left corner is inside the button's own box.
                self.assertEqual(
                    QColor(ghost.pixel(4, 4)).name().upper(),
                    t.color("ghost-bg").upper(),
                )
                bare = self._render("bare", enabled=True)
                self.assertNotEqual(
                    QColor(bare.pixel(4, 4)).name().upper(),
                    t.color("ghost-bg").upper(),
                )


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
            theme_qt.tokens().color("danger").upper(),
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

        bad = theme_qt.tokens().color("danger").upper()
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

    def test_the_editor_is_no_taller_than_the_rows_in_it(self):
        """Two fields and a button row, and a window that stops there.

        A hard-coded height is a guess about type and density that goes stale
        the moment either moves; the leftover went into the input row, which a
        box layout spends by pushing each label away from the field it names.
        """
        from gui.widgets.AlertLimitEditor import AlertLimitEditor

        editor = AlertLimitEditor('max_g', {'name': 'max_g', 'min': 1.0, 'max': 5.0})
        self.addCleanup(destroy, editor)
        editor.show()

        self.assertEqual(editor.height(), editor.sizeHint().height())

        # The label sits on its field, not adrift above it: one gap on the
        # scale, whatever the window is doing.
        holder = editor.min_edit.parentWidget()
        label = holder.layout().itemAt(0).geometry()
        field = holder.layout().itemAt(1).geometry()
        self.assertEqual(field.top() - label.bottom() - 1, holder.layout().spacing())


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


class TestMenuSwitch(ThemeRestoringTestCase):
    """A checkbox standing in for a menu row is coloured like one.

    The switches in the View and Postprocessors menus are real checkboxes
    inside a QWidgetAction, so the form's rules reached them and the menu's did
    not: they came up in the form's ink beside menu items in the muted one,
    which read as the only items in the menu that were not greyed out.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    @staticmethod
    def _menu_with_a_switch():
        menu = QMenu()
        holder = QWidget()
        layout = QVBoxLayout(holder)
        checkbox = QCheckBox("Show all COM ports")
        layout.addWidget(checkbox)
        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        return menu, checkbox

    def test_a_switch_in_a_menu_takes_the_menu_row_colour(self):
        menu, checkbox = self._menu_with_a_switch()
        self.addCleanup(destroy, menu)
        menu.show()

        self.assertEqual(
            checkbox.palette().color(QPalette.ColorRole.WindowText).name().upper(),
            theme_qt.tokens().color("ink-secondary").upper(),
        )
        menu.hide()

    def test_a_focused_switch_is_not_painted_in_the_accent(self):
        # The form's focus colour is the accent, and a menu popup keeps its
        # focus widget: the row last clicked came back blue every time the menu
        # was opened, which reads as a selection. In a menu, focus is coloured
        # like the row under the pointer.
        sheet = theme_qt.build_stylesheet(theme_qt.tokens())
        focus_rules = [
            body for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", sheet)
            if "QMenu QCheckBox:focus" in selector
        ]
        self.assertTrue(focus_rules, "nothing colours a focused switch in a menu")
        for body in focus_rules:
            self.assertIn(theme_qt.tokens().color("ink"), body)
            self.assertNotIn(theme_qt.tokens().color("accent"), body)


class TestRepolish(ThemeRestoringTestCase):

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_a_subtree_with_a_list_in_it_can_be_repolished(self):
        # An item view's update() is Qt's update(index), and PySide hides the
        # no-argument one behind it, so repolishing a panel that happened to
        # contain a list raised a TypeError instead of repainting it.
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QListWidget())
        self.addCleanup(destroy, panel)

        theme_qt.set_panel(panel, "row")

        self.assertEqual(panel.property("panel"), "row")


class TestItemViewRowLayout(ThemeRestoringTestCase):
    """Rows are as tall as the sheet says, whenever the sheet arrives.

    A view asked for a row rectangle before the sheet has reached it lays its
    rows out at the plain style's height and does not ask again, so every row
    afterwards painted at the sheet's height on top of the one above it. The
    settings sidebar came up as five overlapping lines on Windows, and looked
    fixed after a theme change because that repolishes the whole tree.
    """

    def setUp(self):
        super().setUp()
        theme.apply(self.app, theme=T.LIGHT)

    def test_rows_laid_out_before_the_sheet_are_laid_out_again(self):
        nav = QListWidget()
        nav.setObjectName("settingsNav")
        for name in ("General", "Alert limits", "Advanced"):
            nav.addItem(name)
        self.addCleanup(destroy, nav)

        # Anything that asks for geometry before the widget is polished; a
        # Windows build does this on its own on the way to the screen.
        nav.visualItemRect(nav.item(0))

        nav.show()
        rects = [nav.visualItemRect(nav.item(row)) for row in range(nav.count())]
        for above, below in zip(rects, rects[1:]):
            self.assertGreaterEqual(below.y(), above.bottom())


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
        for name in ("tapio-tokens.json", "rollview-tokens.json", "rollview.qss"):
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
