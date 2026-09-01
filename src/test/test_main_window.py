import copy
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

import store
from utils import preferences
from utils.postprocess import BUILTIN, CUSTOM, get_postprocessors
from utils.translation import _
from test.qtcleanup import destroy


class TestMainWindowSettingsFileLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from gui.main_window import MainWindow
        cls.main_window_class = MainWindow

    def setUp(self):
        self.preferences_snapshot = {
            key: copy.deepcopy(preferences.__dict__[key])
            for key in preferences._DEFAULTS
        }
        self.original_preferences_file_path = preferences.preferences_file_path
        self.original_store_selected_directory = store.selected_directory
        self.original_store_selected_profile = store.selected_profile
        self.original_store_profiles = store.profiles

        with patch.object(self.main_window_class, "on_directory_selected"), \
             patch("gui.main_window.SerialWidget.scan_devices"):
            self.window = self.main_window_class()

        self.window.refresh_plot = MagicMock()
        self.window.profile_widget.set_toolbar_visible = MagicMock()
        self.window.serial_widget.view.model.applyFilter = MagicMock()

    def tearDown(self):
        destroy(self.window)
        for widget in QApplication.topLevelWidgets():
            if widget is not self.window and isinstance(widget, QWidget):
                destroy(widget)

        for key, value in self.preferences_snapshot.items():
            preferences.__dict__[key] = value
        preferences.preferences_file_path = self.original_preferences_file_path
        store.selected_directory = self.original_store_selected_directory
        store.selected_profile = self.original_store_selected_profile
        store.profiles = self.original_store_profiles

    def test_file_menu_contains_load_settings_action(self):
        self.assertEqual(self.window.load_settings_file_action.text(), _("MENU_BAR_LOAD_SETTINGS_FILE"))
        self.assertIs(self.window.load_settings_file_action.parent(), self.window)

    def test_load_settings_file_from_missing_path_creates_defaults_and_refreshes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "new", "prefs.json")

            result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            self.assertTrue(os.path.exists(path))
            self.window.refresh_plot.assert_called_once()
            self.window.profile_widget.set_toolbar_visible.assert_called_once_with(preferences.show_plot_toolbar)
            self.window.serial_widget.view.model.applyFilter.assert_called_once()

    def test_invalid_file_prompts_and_cancel_keeps_current_preferences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "invalid.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            preferences.distance_unit = "cm"
            current_path = preferences.get_preferences_file_path()

            with patch("gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
                result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_INVALID)
            self.assertEqual(preferences.distance_unit, "cm")
            self.assertEqual(preferences.get_preferences_file_path(), current_path)
            self.window.refresh_plot.assert_not_called()
            question.assert_called_once()

    def test_invalid_file_confirm_overwrite_closes_settings_window_and_refreshes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "invalid.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")

            settings_window = MagicMock()
            self.window.settings_window = settings_window

            with patch("gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                result = self.window.load_settings_file_from_path(path)

            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)
            settings_window.close.assert_called_once()
            self.assertIsNone(self.window.settings_window)
            self.window.refresh_plot.assert_called_once()
            self.window.profile_widget.set_toolbar_visible.assert_called_once_with(preferences.show_plot_toolbar)
            self.window.serial_widget.view.model.applyFilter.assert_called_once()
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["distance_unit"], preferences.distance_unit)

    def test_apply_loaded_preferences_syncs_view_menu_checkboxes(self):
        preferences.show_all_com_ports = True
        preferences.show_plot_toolbar = False
        preferences.recalculate_mean = False
        preferences.flip_profiles = True

        self.window.apply_loaded_preferences()

        self.assertTrue(self.window.view_menu_checkboxes["show_all_com_ports"].isChecked())
        self.assertFalse(self.window.view_menu_checkboxes["show_plot_toolbar"].isChecked())
        self.assertFalse(self.window.view_menu_checkboxes["recalculate_mean"].isChecked())
        self.assertTrue(self.window.view_menu_checkboxes["flip_profiles"].isChecked())

    def test_flipping_from_the_view_menu_stores_it_and_redraws(self):
        """The menu switch is the settings switch: same preference, one state."""
        original = preferences.flip_profiles
        try:
            with patch.object(self.window, "refresh_plot") as refresh_plot:
                self.window.view_menu_checkboxes["flip_profiles"].setChecked(not original)

            self.assertEqual(preferences.flip_profiles, not original)
            refresh_plot.assert_called_once()
        finally:
            preferences.update_preferences({"flip_profiles": original})

    def test_closing_the_menu_takes_the_focus_off_its_switches(self):
        """A switch clicked in a menu does not stay marked afterwards.

        The switches are real checkboxes inside the menu, and a menu popup is a
        window of its own that keeps its focus widget for as long as it exists:
        the row last clicked came back highlighted every time the menu was
        opened again, marking a state nobody had chosen.
        """
        view_menu = next(menu for menu in self.window.menuBar().findChildren(QMenu)
                         if menu.title() == _('MENU_BAR_VIEW'))
        checkbox = self.window.view_menu_checkboxes['show_all_com_ports']

        view_menu.show()
        checkbox.setFocus()
        # The popup's own focus widget rather than hasFocus(), which also asks
        # whether the window is active — offscreen, none of them are.
        self.assertIs(checkbox.window().focusWidget(), checkbox)

        view_menu.hide()
        self.assertIsNone(checkbox.window().focusWidget())

    def test_the_view_menu_switches_say_what_they_do(self):
        # The labels are names; the sentence explaining each one goes to the
        # guidance row at the foot of the window, not into a popup.
        for checkbox in self.window.view_menu_checkboxes.values():
            self.assertTrue(checkbox.statusTip())
            self.assertEqual(checkbox.toolTip(), "")

    def test_apply_loaded_preferences_syncs_postprocessor_states(self):
        postprocessors = get_postprocessors()
        module_name = next(iter(postprocessors))
        preferences.enabled_postprocessors = []

        self.window.apply_loaded_preferences()

        self.assertFalse(postprocessors[module_name].enabled)
        self.assertFalse(self.window.postprocessor_checkboxes[module_name].isChecked())
        self.assertEqual(self.window.postprocess_manager.enabled_postprocessors, [])

    def test_apply_loaded_preferences_drops_unknown_postprocessor_names(self):
        postprocessors = get_postprocessors()
        module_name = next(iter(postprocessors))
        preferences.enabled_postprocessors = [module_name, "missing_postprocessor"]

        self.window.apply_loaded_preferences()

        self.assertEqual(preferences.enabled_postprocessors, [module_name])
        self.assertTrue(postprocessors[module_name].enabled)
        self.assertTrue(self.window.postprocessor_checkboxes[module_name].isChecked())

    def test_the_menu_rules_custom_postprocessors_apart_from_the_built_in_ones(self):
        """Site-local code and the product are different kinds of thing.

        A module dropped into the operator's own folder can appear, break or
        vanish between launches; one that ships with the software cannot.
        """
        actions = self.window.postprocessors_menu.actions()
        separators = [index for index, action in enumerate(actions) if action.isSeparator()]
        self.assertEqual(len(separators), 2)

        builtin_names = set(get_postprocessors(BUILTIN))
        self.assertTrue(builtin_names)
        self.assertEqual(len(actions[:separators[0]]), len(builtin_names))

        commands = actions[separators[-1] + 1:]
        self.assertEqual(
            [action.text() for action in commands],
            [
                _('MENU_BAR_RUN_POSTPROCESSORS'),
                _('MENU_BAR_REFRESH_POSTPROCESSORS'),
                _('MENU_BAR_OPEN_POSTPROCESSOR_FOLDER'),
            ],
        )

    def test_an_empty_custom_folder_says_so_rather_than_showing_nothing(self):
        """An empty section reads as a broken menu; a line saying so does not."""
        def only_builtins(origin=None):
            return get_postprocessors(BUILTIN) if origin != CUSTOM else {}

        with patch("gui.main_window.get_postprocessors", side_effect=only_builtins):
            self.window.build_postprocessors_menu()

            placeholder = next(
                action for action in self.window.postprocessors_menu.actions()
                if action.text() == _('MENU_BAR_NO_CUSTOM_POSTPROCESSORS')
            )
            self.assertFalse(placeholder.isEnabled())

        self.window.build_postprocessors_menu()

    def test_a_custom_module_is_listed_after_the_divider(self):
        custom = get_postprocessors(CUSTOM)
        if not custom:
            self.skipTest("no custom postprocessor in the user's folder")

        actions = self.window.postprocessors_menu.actions()
        separators = [index for index, action in enumerate(actions) if action.isSeparator()]
        between = actions[separators[0] + 1:separators[-1]]
        self.assertEqual(len(between), len(custom))
        self.assertTrue(
            set(custom).issubset(self.window.postprocessor_checkboxes)
        )

    def test_refresh_rebuilds_the_menu_and_the_checkbox_map(self):
        """QMenu.clear() deletes the checkboxes the old map pointed at.

        Without a rebuilt map the next preference load walks into dangling C++
        objects, which is what this is really testing.
        """
        self.window.refresh_postprocessors_action.trigger()
        QApplication.processEvents()  # the rebuild is deferred by a zero timer

        self.assertEqual(
            set(self.window.postprocessor_checkboxes),
            set(get_postprocessors()),
        )
        for checkbox in self.window.postprocessor_checkboxes.values():
            checkbox.isChecked()  # raises RuntimeError if the C++ side is gone

    def test_refresh_is_refused_while_a_run_is_in_flight(self):
        with patch.object(self.window.postprocess_manager, "is_running", return_value=True), \
             patch("gui.main_window.show_info_msgbox") as info_box, \
             patch("gui.main_window.reload_postprocessors") as reload_modules:
            self.window.refresh_postprocessors_action.trigger()
            QApplication.processEvents()

        info_box.assert_called_once()
        reload_modules.assert_not_called()

    def test_opening_the_postprocessor_folder_creates_it_first(self):
        """A menu item that opens nothing because the folder has never existed
        is a dead end — the point of it is somewhere to drop a .py file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = os.path.join(tmpdir, "postprocessors")
            with patch("gui.main_window.user_postprocessors_path", folder), \
                 patch("gui.main_window.open_in_file_explorer") as opener:
                self.window.open_postprocessor_folder_action.trigger()

            self.assertTrue(os.path.isdir(folder))
            opener.assert_called_once_with(folder)

    def test_one_folder_can_be_postprocessed_on_its_own(self):
        """The menu item sweeps the working directory and applies the cutoff.

        Pointed at a folder, the context menu runs that folder whatever its
        date — an operator asking for a specific roll has already decided.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            roll = os.path.join(tmpdir, "250521-081510")
            os.makedirs(roll)

            with patch.object(self.window.postprocess_manager, "run_postprocessors") as run:
                self.window.directory_view.postprocess_requested.emit(roll)

            run.assert_called_once_with([roll])

    def test_a_folder_that_is_not_a_roll_is_not_postprocessed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            postprocessors_dir = os.path.join(tmpdir, "postprocessors")
            os.makedirs(postprocessors_dir)
            missing = os.path.join(tmpdir, "gone")

            with patch.object(self.window.postprocess_manager, "run_postprocessors") as run:
                self.window.directory_view.postprocess_requested.emit(postprocessors_dir)
                self.window.directory_view.postprocess_requested.emit(missing)
                self.window.directory_view.postprocess_requested.emit("")

            run.assert_not_called()

    def test_the_status_bar_carries_the_work_and_then_the_outcome(self):
        """One area, three kinds of work, and a summary that outlives the bar."""
        stopped = []
        self.window.start_activity("Scanning", cancel=lambda: stopped.append(True))

        self.assertTrue(self.window.activity_progress_bar.isVisibleTo(self.window))
        self.assertTrue(self.window.activity_stop_button.isVisibleTo(self.window))
        self.assertEqual(self.window.status_message(), "Scanning")

        self.window.update_activity(40, "Half way")
        self.assertEqual(self.window.activity_progress_bar.value(), 40)

        self.window.activity_stop_button.click()
        self.assertEqual(stopped, [True])
        self.assertFalse(self.window.activity_stop_button.isEnabled())

        self.window.finish_activity("Done, 3 rolls")
        self.assertFalse(self.window.activity_progress_bar.isVisibleTo(self.window))
        self.assertFalse(self.window.activity_stop_button.isVisibleTo(self.window))
        self.assertEqual(self.window.status_message(), "Done, 3 rolls")

    def test_work_that_cannot_be_stopped_offers_no_square(self):
        self.window.start_activity("Scanning")
        self.assertFalse(self.window.activity_stop_button.isVisibleTo(self.window))
        self.window.finish_activity()

    def test_the_scan_that_runs_at_startup_can_be_stopped_too(self):
        """The window used to scan before it had wired the scan up.

        The bar then moved with no square beside it, which is the one state
        this row is not allowed to be in: something is running and nothing can
        stop it.
        """
        from gui.widgets.serialports import SerialWidget

        def scan_and_announce(widget):
            widget.scan_started.emit()

        with patch.object(SerialWidget, "scan_devices", scan_and_announce), \
             patch.object(self.main_window_class, "on_directory_selected"):
            window = self.main_window_class()

        try:
            self.assertTrue(window.activity_progress_bar.isVisibleTo(window))
            self.assertTrue(window.activity_stop_button.isVisibleTo(window))
            self.assertTrue(window.activity_stop_button.isEnabled())
        finally:
            # Closing a QMainWindow is not destroying it, and a window left
            # alive here is ~180 widgets the leak check will find in whichever
            # module happens to run next — and 180 widgets the collector may
            # take apart on whatever thread it happens to run on.
            destroy(window)
            del window
            # Destroying a parent posts DeferredDelete for its children, so
            # drain until the queue stops producing new deletions.
            for _ in range(5):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

    def test_a_scan_can_be_stopped_like_anything_else(self):
        """Every moving bar has the same square beside it, whatever is moving."""
        with patch.object(self.window.serial_widget, "stop_scan") as stop_scan:
            self.window.on_scan_started()
            self.assertTrue(self.window.activity_stop_button.isVisibleTo(self.window))
            self.window.activity_stop_button.click()

        stop_scan.assert_called_once()
        self.window.finish_activity()

    def test_hover_guidance_does_not_wipe_out_what_the_work_is_saying(self):
        """Qt's own handler shows a status tip as the status bar message.

        Moving the mouse over the chart then erased the sync in progress, which
        is why the tip gets a label of its own at the other end of the row.
        """
        from PySide6.QtGui import QStatusTipEvent

        self.window.set_status_message("Receiving 4 / 12")
        handled = self.window.event(QStatusTipEvent("Scroll to zoom."))

        self.assertTrue(handled)
        # guidance() is the whole line; the label shows as much of it as the
        # row has room for, which on a window this narrow is not all of it.
        self.assertEqual(self.window.guidance(), "Scroll to zoom.")
        self.assertEqual(self.window.status_message(), "Receiving 4 / 12")

    def test_the_chart_guidance_is_confined_to_the_axes(self):
        """How to zoom is said where zooming does something, and nowhere else.

        The tip used to sit on the whole profile tab, so it followed the
        pointer up onto the stat tiles: an operator reading a tile was told
        about scrolling a chart they were not pointing at. It is not on the
        canvas widget either — the margins, the axis labels and the toolbar are
        not the plot. Matplotlib says when the pointer crosses into the axes,
        which is the same moment the toolbar starts reading out x and y.
        """
        profile_widget = self.window.profile_widget

        self.assertEqual(profile_widget.statusTip(), "")
        self.assertEqual(profile_widget.canvas.statusTip(), "")

        self.window.show_guidance("")
        profile_widget._on_axes_enter()
        self.assertEqual(self.window.guidance(), _("CHART_STATUS_TIP_TEXT"))

        profile_widget._on_axes_leave()
        self.assertEqual(self.window.guidance(), "")

    def test_a_tile_says_what_a_click_does_the_moment_it_is_entered(self):
        """The row, and nothing that hovers over the measurement.

        Qt raises a tooltip only once the pointer has rested for the best part
        of a second, so sweeping across the tiles showed nothing at all. The
        guidance goes out on arrival — and Qt emits the tip of the widget
        actually entered, never a parent's, which is why every part of the tile
        carries it.
        """
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QEnterEvent

        tile = self.window.profile_widget.stats_widget.widgets[0]

        def enter(widget):
            point = QPointF(widget.rect().center())
            QApplication.sendEvent(
                widget,
                QEnterEvent(point, point, widget.mapToGlobal(point.toPoint())),
            )

        for part in (tile, tile.label, tile.value_label, tile.unit_label,
                     tile.foot_label, tile.foot_label.min_chunk):
            with self.subTest(part=part.__class__.__name__):
                self.window.show_guidance("")
                enter(part)
                self.assertIn(_("GUIDANCE_EDIT_ALERT_LIMITS"), self.window.guidance())
                self.assertEqual(part.toolTip(), "")

                QApplication.sendEvent(part, QEvent(QEvent.Type.Leave))
                self.assertEqual(self.window.guidance(), "")

    def test_a_tile_answers_a_hover_anywhere_on_it_and_not_only_on_its_text(self):
        """The whole tile is one hover, padding and empty space included.

        The pointer moving off a label onto the tile around it is a Leave on
        the label and no Enter on the tile — the tile was never left — and a
        Leave empties the row. So the line appeared over the eyebrow and the
        number, and went out again in the space beside them, which is most of a
        tile. The labels hand the pointer through to the tile instead.

        Driven with real pointer motion rather than a sent Enter, because it is
        the enter and leave Qt works out for itself that used to go wrong.
        """
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        self.window.show()
        QApplication.processEvents()

        tile = self.window.profile_widget.stats_widget.widgets[0]
        line = tile.statusTip()
        self.assertTrue(line)

        # Along the tile: its own padding, its labels, and the space beside the
        # number that no label covers.
        crossing = [
            ("top-left padding", QPoint(1, 1)),
            ("eyebrow", tile.label.geometry().center()),
            ("beside the number", QPoint(tile.width() - 2, tile.height() // 2)),
            ("limit footer", tile.foot_label.geometry().center()),
            ("bottom-right corner", QPoint(tile.width() - 2, tile.height() - 2)),
        ]
        for where, point in crossing:
            with self.subTest(where=where):
                QTest.mouseMove(tile, point)
                QApplication.processEvents()
                self.assertEqual(self.window.guidance(), line)

    def test_nothing_in_the_window_raises_a_hover_popup(self):
        """Guidance goes in the row at the foot; nothing hovers over the work.

        Matplotlib gives its toolbar buttons tooltips of their own and an action
        with no tooltip falls back to its own text, so the toolbar refuses the
        event rather than trying to keep a string empty. What each button does
        is in the row instead.
        """
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtWidgets import QToolTip

        answered = []
        for widget in self.window.findChildren(QWidget):
            if not widget.isVisible():
                continue
            QToolTip.hideText()
            centre = widget.rect().center()
            event = QHelpEvent(QEvent.Type.ToolTip, centre,
                               widget.mapToGlobal(centre))
            event.setAccepted(False)
            QApplication.sendEvent(widget, event)
            if QToolTip.isVisible() and QToolTip.text():
                answered.append((widget.__class__.__name__, QToolTip.text()))
        QToolTip.hideText()

        self.assertEqual(answered, [])

    def test_the_plot_toolbar_says_what_it_does_in_the_row(self):
        # Moved, not dropped: the text Matplotlib wrote for each button is what
        # the row says, flattened to the one line the row has.
        actions = [action for action in self.window.profile_widget.toolbar.actions()
                   if action.text()]
        self.assertTrue(actions)
        for action in actions:
            with self.subTest(action=action.text()):
                self.assertTrue(action.statusTip())
                self.assertNotIn("\n", action.statusTip())

    def test_transfer_progress_counts_the_file_in_flight(self):
        self.window._transfer_total_files = 4
        self.window._transfer_file_number = 1
        self.assertEqual(self.window._transfer_percent(0.0), 0)
        self.assertEqual(self.window._transfer_percent(0.5), 12)
        self.window._transfer_file_number = 4
        self.assertEqual(self.window._transfer_percent(1.0), 100)

    def test_a_finished_sync_says_what_it_brought_in(self):
        from models.FileTransfer import FileTransferItem

        manager = self.window.file_transfer_manager
        manager.model.removeItems()
        for index in range(3):
            manager.model.addItem(FileTransferItem(f"{index}.prof", 3 - index))
        manager.last_deleted_count = 0

        # The postprocessors follow a sync; this test is about what the sync
        # says, and starting a real run here would leave a thread and a failure
        # dialog behind for whichever test next spins an event loop.
        with patch.object(self.window.postprocess_manager, "run_postprocessors"):
            self.window.on_file_transfer_finished(["/rolls/a", "/rolls/b"])

        # Postprocessing starts on the same breath and takes the bar over, so
        # what the sync did is held and stays in front of it.
        summary = _("SYNC_FINISHED_STATUS").format(files=3, folders=2)
        self.assertEqual(self.window._sync_summary, summary)
        self.assertEqual(self.window.status_message(), summary)

    def test_a_failed_postprocessor_is_not_left_to_the_status_bar_alone(self):
        """A roll that silently has no report is worth interrupting for."""
        from utils.postprocess import PostprocessResult

        self.window.postprocess_manager.was_cancelled = False
        result = PostprocessResult(
            processed_folders=["/rolls/a"], failed_folders=["/rolls/b"])

        with patch.object(QMessageBox, "warning") as warning:
            self.window.on_postprocess_finished(result)

        warning.assert_called_once()
        self.assertIn(
            _("POSTPROCESSORS_ERROR_TEXT").format(count=1),
            self.window.status_message(),
        )

    def test_a_clean_postprocessor_run_does_not_interrupt(self):
        from utils.postprocess import PostprocessResult

        self.window.postprocess_manager.was_cancelled = False
        result = PostprocessResult(processed_folders=["/rolls/a", "/rolls/b"])

        with patch.object(QMessageBox, "warning") as warning:
            self.window.on_postprocess_finished(result)

        warning.assert_not_called()
        self.assertEqual(
            self.window.status_message(),
            _("POSTPROCESSORS_FINISHED_STATUS").format(count=2),
        )

    def test_directory_name_initialized_before_load_settings_file(self):
        self.assertIsNone(self.window.directory_name)

    def test_load_settings_file_from_path_without_prior_directory_selection(self):
        # Verifies no crash (AttributeError on directory_name / refresh_plot guard) occurs
        # when load is triggered before any directory is selected.
        self.window.refresh_plot = self.main_window_class.refresh_plot.__get__(self.window)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "prefs.json")
            result = self.window.load_settings_file_from_path(path)
            self.assertEqual(result.status, preferences.LOAD_STATUS_CREATED_DEFAULTS)

    def test_statistics_directory_selection_updates_app_plot_and_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected_directory = os.path.join(tmpdir, "roll-1")
            os.mkdir(selected_directory)
            self.window.on_directory_selected = MagicMock()
            self.window.statistics_analysis_widget.highlight_point = MagicMock()

            signal_block_states = []

            def capture_signal_block_state(path):
                signal_block_states.append(self.window.directory_view.signalsBlocked())

            self.window.directory_view.select_directory_by_path = MagicMock(side_effect=capture_signal_block_state)

            self.window.on_statistics_directory_selected(selected_directory)

            self.window.on_directory_selected.assert_called_once_with(selected_directory)
            self.window.statistics_analysis_widget.highlight_point.assert_called_once_with(selected_directory)
            self.window.directory_view.select_directory_by_path.assert_called_once_with(selected_directory)
            self.assertEqual(signal_block_states, [True])

    def test_directory_selection_clears_selected_profile_when_directory_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_directory = os.path.join(tmpdir, "old")
            new_directory = os.path.join(tmpdir, "new")
            os.mkdir(old_directory)
            os.mkdir(new_directory)

            store.selected_directory = old_directory
            store.selected_profile = "selected.prof"
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.update_plot = MagicMock()

            self.window.on_directory_selected(new_directory)

            self.assertIsNone(store.selected_profile)

    def test_directory_selection_keeps_selected_profile_when_directory_is_same(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.selected_directory = tmpdir
            store.selected_profile = "selected.prof"
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.update_plot = MagicMock()

            self.window.on_directory_selected(tmpdir)

            self.assertEqual(store.selected_profile, "selected.prof")

    def test_root_directory_change_selects_root_when_root_has_no_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.selected_directory = None
            store.selected_profile = "selected.prof"
            store.profiles = ["stale"]
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.update_plot = MagicMock()

            self.window.on_root_directory_changed(tmpdir)

            self.assertEqual(store.root_directory, tmpdir)
            self.assertEqual(store.selected_directory, tmpdir)
            self.assertIsNone(store.selected_profile)
            self.assertEqual(store.profiles, [])
            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.update_plot.assert_called_once_with(
                [],
                os.path.basename(tmpdir),
            )

    def test_root_directory_change_selects_root_when_root_has_profile_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "root.prof")
            with open(profile_path, "wb"):
                pass

            store.selected_directory = None
            self.window.on_directory_selected = MagicMock()
            self.window._clear_profile_selection = MagicMock()
            self.window.profile_widget.show_no_profile_files_message = MagicMock()

            self.window.on_root_directory_changed(tmpdir)

            self.assertEqual(store.root_directory, tmpdir)
            self.window.on_directory_selected.assert_called_once_with(tmpdir)
            self.window._clear_profile_selection.assert_not_called()
            self.window.profile_widget.show_no_profile_files_message.assert_not_called()

    def test_root_directory_change_does_not_blank_plot_when_profile_folders_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "roll-1"))
            store.selected_directory = None
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_root_directory_changed(tmpdir)

            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.clear_plot_display.assert_not_called()

    def test_directory_contents_changed_clears_plot_when_last_folder_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.root_directory = tmpdir
            store.selected_directory = os.path.join(tmpdir, "deleted")
            store.selected_profile = "selected.prof"
            store.profiles = ["stale"]
            self.window.fileView.set_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_directory_contents_changed()

            self.assertIsNone(store.selected_directory)
            self.assertIsNone(store.selected_profile)
            self.assertEqual(store.profiles, [])
            self.window.fileView.set_directory.assert_called_once_with(tmpdir)
            self.window.profile_widget.clear_plot_display.assert_called_once()

    def test_directory_contents_changed_selects_first_folder_when_selected_folder_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "remaining"))
            store.root_directory = tmpdir
            store.selected_directory = os.path.join(tmpdir, "deleted")
            self.window.directory_view.select_first_directory = MagicMock()
            self.window.profile_widget.clear_plot_display = MagicMock()

            self.window.on_directory_contents_changed()

            self.window.directory_view.select_first_directory.assert_called_once()
            self.window.profile_widget.clear_plot_display.assert_not_called()

    def test_file_transfer_finished_refreshes_directory_dates_before_postprocessing(self):
        folder_paths = ["/tmp/roll-1"]
        call_order = []
        self.window.directory_view.refresh_directory_dates = MagicMock(
            side_effect=lambda paths: call_order.append("refresh")
        )
        self.window.postprocess_manager.run_postprocessors = MagicMock(
            side_effect=lambda paths: call_order.append("postprocess")
        )
        self.window.on_directory_contents_changed = MagicMock(
            side_effect=lambda: call_order.append("reload")
        )

        self.window.on_file_transfer_finished(folder_paths)

        self.window.directory_view.refresh_directory_dates.assert_called_once_with(folder_paths)
        self.window.postprocess_manager.run_postprocessors.assert_called_once_with(folder_paths)
        self.window.on_directory_contents_changed.assert_called_once()
        self.assertEqual(call_order, ["refresh", "postprocess", "reload"])

    def test_empty_successful_manual_sync_shows_up_to_date_message_box(self):
        self.window.file_transfer_manager.last_transfer_outcome = "ok"
        self.window.file_transfer_manager.last_transfer_was_auto = False
        self.window.directory_view.refresh_directory_dates = MagicMock()
        self.window.postprocess_manager.run_postprocessors = MagicMock()
        self.window.on_directory_contents_changed = MagicMock()

        with patch("gui.main_window.QMessageBox.information") as information:
            self.window.on_file_transfer_finished([])

        information.assert_called_once_with(
            self.window,
            _("SYNC_UP_TO_DATE_TITLE"),
            _("SYNC_UP_TO_DATE_TEXT"),
        )
        self.assertEqual(self.window.status_message(), "")
        self.window.directory_view.refresh_directory_dates.assert_not_called()
        self.window.postprocess_manager.run_postprocessors.assert_not_called()
        self.window.on_directory_contents_changed.assert_not_called()

    def test_connection_lost_message_names_the_device(self):
        from utils.rqft_support import DeviceIdentity

        self.window.device_connection_manager.identities["COM4"] = DeviceIdentity(
            device_name="Tapio RQP Live",
            serial_number="SN1",
            firmware_version="v1.2.0",
        )

        self.window.on_connection_lost("COM4", "unplugged")

        self.assertEqual(
            self.window.status_message(),
            _("DEVICE_DISCONNECTED_STATUS").format(device="Tapio RQP Live (SN1)"),
        )

    def test_connection_lost_falls_back_to_the_port_name(self):
        self.window.on_connection_lost("COM9", "dead")

        self.assertEqual(
            self.window.status_message(),
            _("DEVICE_DISCONNECTED_STATUS").format(device="COM9"),
        )

    def test_transfer_error_signal_reaches_the_status_bar(self):
        # The slot takes only the message; the signal also carries is_auto.
        self.window.file_transfer_manager.transferError.emit("sync broke", True)
        QApplication.processEvents()

        self.assertEqual(self.window.status_message(), "sync broke")

    def test_empty_successful_auto_sync_does_not_show_message_box(self):
        self.window.file_transfer_manager.last_transfer_outcome = "ok"
        self.window.file_transfer_manager.last_transfer_was_auto = True
        self.window.on_file_transfer_started()

        with patch("gui.main_window.QMessageBox.information") as information:
            self.window.on_file_transfer_finished([])

        information.assert_not_called()
        self.assertEqual(self.window.status_message(), "")


if __name__ == "__main__":
    unittest.main()
