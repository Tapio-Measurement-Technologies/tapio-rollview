# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.


from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget, QCheckBox, QVBoxLayout, QHBoxLayout, QWidgetAction, QSplitter, QTabWidget, QProgressBar, QPushButton, QLabel, QFileDialog, QMessageBox
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import QDir, Qt, QEvent, QSignalBlocker, QTimer

import theme
from theme import qt as theme_qt

from utils.file_utils import list_prof_files, open_in_file_explorer, format_bytes
from utils.postprocess import (toggle_postprocessor, PostprocessManager, get_postprocessors,
                               PostprocessResult, reload_postprocessors, user_postprocessors_path,
                               BUILTIN, CUSTOM)
from utils import preferences
from utils.figure_export import copy_plot_widget_to_clipboard
import os
from datetime import datetime, timedelta
from gui.widgets.sidebar import Sidebar
from gui.widgets.FileView import FileView
from gui.widgets.ProfileWidget import ProfileWidget
from gui.log_window import LogWindow
from models.Profile import Profile
import settings
import store
from workers.file_transfer import FileTransferManager
from workers.device_connection import DeviceConnectionManager
from gui.widgets.serialports import SerialWidget
from gui.widgets.DirectoryView import DirectoryView
from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget
from gui.settings import SettingsWindow
from gui.qr_config_dialog import QRConfigDialog
from gui.widgets.messagebox import show_info_msgbox, show_error_msgbox
from utils.translation import _

#: The stop square in the status bar: a control-height target for the button,
#: with the glyph drawn small inside it so it reads as a mark, not a button
#: with an icon in it.
ACTIVITY_STOP_SIZE = 22
ACTIVITY_STOP_GLYPH = 16


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"{_('WINDOW_TITLE_MAIN')} {store.app_version}")
        # Also set on the application in main(), but a window that carries its
        # own icon is right whichever entry point built it.
        self.setWindowIcon(QIcon(settings.ICON_PATH))
        # Window minimum 1024x640; below that the layout stops being an
        # analysis tool and starts being a puzzle. It opens larger than that:
        # the device list, the folder list and the file list all have to be
        # visible at once for the window to make sense at a glance.
        self.setMinimumSize(1024, 640)
        self.resize(1200, 720)

        # QMainWindowLayout ignores these for the central widget, so this is
        # tidiness rather than a fix — but an audit that walks every layout
        # should not have to carry an exception for it.
        theme_qt.pad(self.layout(), 0)
        theme_qt.gap(self.layout(), 0)

        self.file_transfer_manager = FileTransferManager()
        self.device_connection_manager = DeviceConnectionManager()
        self.file_transfer_manager.set_connection_manager(self.device_connection_manager)
        self.device_connection_manager.set_transfer_manager(self.file_transfer_manager)
        self.postprocess_manager = PostprocessManager(self)
        self.log_window = None
        self.settings_window = None
        self.directory_name = None
        self.view_menu_checkboxes = {}
        self.postprocessor_checkboxes = {}

        self.serial_widget = SerialWidget(
            self.file_transfer_manager, self.device_connection_manager
        )
        self.directory_view = DirectoryView()
        self.sidebar = Sidebar()
        self.sidebar.addWidget(self.serial_widget, 170)
        self.sidebar.addWidget(self.directory_view)

        self.tab_view = QTabWidget()
        # QTabWidget builds the page stack itself, on Qt's defaults, and inset
        # every tab's contents by an off-grid 9 px a side. The tabs carry their
        # own padding, so the container carries none.
        tab_pages = self.tab_view.findChild(QStackedWidget).layout()
        theme_qt.pad(tab_pages, 0)
        theme_qt.gap(tab_pages, 0)
        self.statistics_analysis_widget = StatisticsAnalysisWidget()
        self.statistics_analysis_widget.directory_selected.connect(self.on_statistics_directory_selected)
        self.profile_widget = ProfileWidget()
        self.tab_view.addTab(self.profile_widget, _("TAB_TITLE_PROFILES"))
        self.tab_view.addTab(self.statistics_analysis_widget, _("TAB_TITLE_STATISTICS"))
        self.tab_view.currentChanged.connect(self.statistics_analysis_widget.update)

        self.fileView = FileView()
        self.fileView.file_selected.connect(self.on_file_selected)
        self.fileView.profile_state_changed.connect(self.refresh_plot)
        self.fileView.sort_changed.connect(self.on_file_sort_changed)

        self.directory_view.directory_selected.connect(self.on_directory_selected)
        self.directory_view.directory_selected.connect(self.statistics_analysis_widget.highlight_point)
        self.directory_view.root_directory_changed.connect(self.on_root_directory_changed)
        self.directory_view.root_directory_changed.connect(self.statistics_analysis_widget.update)
        self.directory_view.directory_contents_changed.connect(self.on_directory_contents_changed)
        self.directory_view.directory_contents_changed.connect(self.statistics_analysis_widget.update)
        self.directory_view.roll_filter_changed.connect(self.statistics_analysis_widget.set_roll_filter)
        self.directory_view.postprocess_requested.connect(self.run_postprocessors_for_folder)

        # Attempt to create default root dir if it does not exist
        if QDir().mkpath(store.root_directory):
            self.directory_view.change_root_directory(store.root_directory)
        else:
            current_path = QDir.currentPath()
            print(f"Failed to create default roll directory to {store.root_directory}!")
            print(f"Defaulting to {current_path}")
            self.directory_view.change_root_directory(current_path)

        ver_splitter = QSplitter(Qt.Orientation.Vertical)
        ver_splitter.addWidget(self.tab_view)
        ver_splitter.addWidget(self.fileView)
        ver_splitter.setStretchFactor(0, 1)
        ver_splitter.setStretchFactor(1, 0)
        ver_splitter.setCollapsible(0, False)
        ver_splitter.setCollapsible(1, False)
        # The chart is the subject of this window, so it opens with the larger
        # share; the file list is a picker, not a view, and every row it gives
        # back goes to the chart above it.
        ver_splitter.setSizes([696, 184])

        hor_splitter = QSplitter(Qt.Orientation.Horizontal)
        hor_splitter.addWidget(self.sidebar)
        hor_splitter.addWidget(ver_splitter)
        hor_splitter.setStretchFactor(0, 0)
        hor_splitter.setStretchFactor(1, 1)
        # Wide enough for the folder list's two columns — the roll name and a
        # full timestamp — with room to spare, since the date column stretches
        # into whatever is left and clips the moment there is nothing left.
        hor_splitter.setSizes([360, 1080])
        hor_splitter.setCollapsible(0, False)
        hor_splitter.setCollapsible(1, False)

        # A theme set to "system" tracks the desktop for as long as the window
        # is open, not only at startup.
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._follow_system_appearance
        )

        # QMainWindow makes one for itself the first time it is asked; handing
        # it a second leaves the first parented and unused, which is a widget
        # nobody can see and every audit has to explain.
        self.status_bar = self.statusBar()
        self.status_bar.setFixedHeight(30)

        # One place in the window says what background work is going on: the
        # port scan, a sync, the postprocessors afterwards. They used to be
        # three different answers — two of them modal windows in front of the
        # measurement the operator was reading — and none of them said what had
        # happened once it was over.
        # A square, next to the bar, wherever the bar is: one gesture stops a
        # scan, a sync or the postprocessors, and it is in the same place every
        # time rather than in whichever window happened to be open.
        self.activity_stop_button = QPushButton()
        self.activity_stop_button.setObjectName("activityStop")
        self.activity_stop_button.setFixedSize(
            ACTIVITY_STOP_SIZE, ACTIVITY_STOP_SIZE)
        self.activity_stop_button.setToolTip(_("BUTTON_TEXT_STOP"))
        self.activity_stop_button.setVisible(False)
        self.activity_stop_button.clicked.connect(self.on_activity_cancelled)
        self._refresh_stop_icon()

        # The row is built out of labels rather than QStatusBar's own message,
        # which is painted across the non-permanent area and hides any widget
        # sharing it — the bar could then only ever sit to one side. Two
        # stretchy labels with the work between them is what centres it.
        self.activity_label = QLabel()
        self.status_bar.addWidget(self.activity_label, 1)

        self.activity_progress_bar = QProgressBar()
        self.activity_progress_bar.setTextVisible(False)
        self.activity_progress_bar.setFixedWidth(240)

        # The square belongs to the bar, so they travel as one item, closer to
        # each other than to anything else in the row.
        activity_group = QWidget()
        activity_layout = QHBoxLayout(activity_group)
        theme_qt.pad(activity_layout, 0)
        theme_qt.gap(activity_layout, 1)
        activity_layout.addWidget(self.activity_progress_bar)
        activity_layout.addWidget(self.activity_stop_button)
        self.activity_progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(activity_group)

        # Hover guidance goes here rather than into the message area. Qt sends a
        # widget's status tip to the window, whose default handler shows it as a
        # status bar message — so moving the mouse over the chart wiped out
        # whatever the sync or the postprocessors were saying. It gets its own
        # label at the far end, and the stretch on that label is what leaves the
        # bar in the middle: a stretchy message area on one side, a stretchy
        # guide on the other, the work between them.
        self.guide_label = QLabel()
        theme_qt.set_role(self.guide_label, "hint")
        self.guide_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_bar.addPermanentWidget(self.guide_label, 1)

        self._activity_cancel = None
        #: What the last sync brought in, held until the postprocessors that
        #: follow it have finished, so the two are read out together.
        self._sync_summary = None
        self._postprocess_folder_count = 0
        self._transfer_total_files = 0
        self._transfer_file_number = 0
        self._transfer_file_name = ""

        # After the items, not before: QStatusBar rebuilds its own box layout
        # when one is added and puts the spacing back to Qt's default.
        theme_qt.pad(self.status_bar.layout(), 0)
        theme_qt.gap(self.status_bar.layout(), 2)

        self.setCentralWidget(hor_splitter)
        self.init_menu()

        # Wired before the scan, not after: the startup scan announces itself
        # the moment it starts, and a scan whose start nobody heard put a
        # moving bar in the row with no way to stop it.
        self.serial_widget.device_count_changed.connect(self.on_device_count_changed)
        self.serial_widget.scan_started.connect(self.on_scan_started)
        self.serial_widget.scan_progress.connect(self.on_scan_progress)
        self.serial_widget.scan_finished.connect(self.on_scan_finished)

        # Scan devices on startup
        self.serial_widget.scan_devices()

        # Run postprocessors when file transfer is finished
        self.file_transfer_manager.transferStarted.connect(self.on_file_transfer_started)
        self.file_transfer_manager.transferFinished.connect(self.on_file_transfer_finished)
        self.file_transfer_manager.transferError.connect(self.on_transfer_error)

        self.device_connection_manager.connectionLost.connect(self.on_connection_lost)
        self.device_connection_manager.listWarnings.connect(self.on_sync_list_warnings)

        self.postprocess_manager.postprocess_started.connect(self.on_postprocess_started)
        self.postprocess_manager.postprocess_progress.connect(self.on_postprocess_progress)
        self.postprocess_manager.postprocess_finished.connect(self.on_postprocess_finished)

        # The file list the transfer fills in is where the per-file progress
        # comes from — the same two signals the transfer dialog used to read.
        self.file_transfer_manager.model.rowsInserted.connect(self.on_transfer_file_started)
        self.file_transfer_manager.fileByteProgress.connect(self.on_transfer_byte_progress)
        self.file_transfer_manager.syncBatchStarted.connect(self.on_sync_batch_started)

    # ---- the status bar's one activity area ------------------------------

    def set_status_message(self, message=""):
        """What the window is doing or has just done, on the left of the row."""
        self.activity_label.setText(message)

    def status_message(self):
        return self.activity_label.text()


    def start_activity(self, message, cancel=None):
        """Say that background work has started, and how to stop it.

        *cancel* is called if the operator presses the button beside the bar;
        without one the button stays hidden, because a button that cannot be
        pressed is worse than no button.
        """
        self._activity_cancel = cancel
        self.activity_stop_button.setEnabled(cancel is not None)
        self.activity_stop_button.setVisible(cancel is not None)
        self.activity_progress_bar.setValue(0)
        self.activity_progress_bar.setVisible(True)
        self.activity_stop_button.setToolTip(_("BUTTON_TEXT_STOP"))
        self.set_status_message(message)

    def update_activity(self, value, message=None):
        # Deliberately does not raise the bar: start_activity is the only thing
        # that does, and it is the only thing that takes a way to stop the work.
        # That keeps "a bar is moving" and "there is a square to press" from
        # ever coming apart.
        self.activity_progress_bar.setValue(max(0, min(100, int(value))))
        if message:
            self.set_status_message(message)

    def finish_activity(self, message=""):
        """Put the bar away and leave the outcome in words.

        The summary stays in the status bar rather than vanishing with the
        progress: what happened is the part worth reading, and it is the part
        the old dialogs threw away when they closed themselves.
        """
        self._activity_cancel = None
        self.activity_stop_button.setVisible(False)
        self.activity_progress_bar.setVisible(False)
        if message:
            self.set_status_message(message)
        else:
            self.set_status_message()

    def on_activity_cancelled(self):
        cancel = self._activity_cancel
        if cancel is None:
            return
        self.activity_stop_button.setEnabled(False)
        cancel()

    def on_scan_started(self):
        self.start_activity(
            _("SCAN_STARTED_STATUS"), cancel=self.serial_widget.stop_scan)

    def on_scan_progress(self, value, text):
        self.update_activity(value, text)

    def on_scan_finished(self):
        self.finish_activity()

    def _refresh_stop_icon(self):
        """The glyph is baked with a colour, so it is redrawn per theme."""
        self.activity_stop_button.setIcon(
            theme.icons.icon("stop", ACTIVITY_STOP_GLYPH,
                             theme_qt.tokens().color("ink-secondary"))
        )

    def event(self, event):
        """Route status tips to the guide label instead of the message area.

        QMainWindow's own handler calls showMessage() with the tip, which is
        the behaviour this is here to prevent — a sync in progress should not
        be erased by the mouse passing over the chart.
        """
        if event.type() == QEvent.Type.StatusTip:
            self.guide_label.setText(event.tip())
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        """Handle Ctrl+C to copy current tab view to clipboard."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            current_widget = self.tab_view.currentWidget()
            if current_widget:
                copy_plot_widget_to_clipboard(current_widget)
        else:
            super().keyPressEvent(event)


    def init_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu(_('MENU_BAR_FILE'))

        settings_action = QAction(_('MENU_BAR_SETTINGS'), self)
        settings_action.triggered.connect(self.open_settings_window)
        file_menu.addAction(settings_action)

        self.load_settings_file_action = QAction(_('MENU_BAR_LOAD_SETTINGS_FILE'), self)
        self.load_settings_file_action.triggered.connect(self.load_settings_file)
        file_menu.addAction(self.load_settings_file_action)

        export_settings_action = QAction(_('MENU_BAR_EXPORT_SETTINGS_FILE'), self)
        export_settings_action.triggered.connect(self.export_settings_file)
        file_menu.addAction(export_settings_action)

        view_menu = menu_bar.addMenu(_('MENU_BAR_VIEW'))
        show_all_com_ports_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_SHOW_ALL_COM_PORTS'),
            # 'Show all COM ports'
            view_menu,
            preferences.show_all_com_ports,
            self.on_show_all_com_ports_changed
        )
        self.view_menu_checkboxes['show_all_com_ports'] = show_all_com_ports_checkbox.defaultWidget().findChild(QCheckBox)

        show_plot_toolbar_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_SHOW_PLOT_TOOLBAR'),
            # 'Show toolbar',
            view_menu,
            preferences.show_plot_toolbar,
            self.on_show_plot_toolbar_changed
        )
        self.view_menu_checkboxes['show_plot_toolbar'] = show_plot_toolbar_checkbox.defaultWidget().findChild(QCheckBox)

        recalculate_mean_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_RECALCULATE_MEAN'),
            # 'Recalculate mean on profile show/hide',
            view_menu,
            preferences.recalculate_mean,
            self.on_recalculate_mean_changed
        )
        self.view_menu_checkboxes['recalculate_mean'] = recalculate_mean_checkbox.defaultWidget().findChild(QCheckBox)

        log_window_action = QAction(_("APPLICATION_LOGS"), self)
        log_window_action.triggered.connect(self.open_log_window)

        view_menu.addAction(show_all_com_ports_checkbox)
        view_menu.addAction(show_plot_toolbar_checkbox)
        view_menu.addAction(recalculate_mean_checkbox)
        view_menu.addAction(log_window_action)

        self.postprocessors_menu = menu_bar.addMenu(_('MENU_BAR_POSTPROCESSORS'))

        # Parented to the window rather than to the menu: refreshing clears the
        # menu, and QMenu.clear() deletes the actions the menu owns — which is
        # what has to happen to the module checkboxes and must not happen to
        # these three.
        self.run_postprocessors_action = QAction(_('MENU_BAR_RUN_POSTPROCESSORS'), self)
        self.run_postprocessors_action.triggered.connect(
            self.run_postprocessors_for_all_folders)

        self.refresh_postprocessors_action = QAction(_('MENU_BAR_REFRESH_POSTPROCESSORS'), self)
        self.refresh_postprocessors_action.triggered.connect(self.on_refresh_postprocessors)

        self.open_postprocessor_folder_action = QAction(
            _('MENU_BAR_OPEN_POSTPROCESSOR_FOLDER'), self)
        self.open_postprocessor_folder_action.triggered.connect(self.open_postprocessor_folder)

        self.build_postprocessors_menu()

        scan_menu = menu_bar.addMenu(_('MENU_BAR_DEVICE_CONFIG'))
        apply_alert_limits_action = QAction(_('MENU_BAR_APPLY_ALERT_LIMITS_TO_DEVICE'), self)
        apply_alert_limits_action.triggered.connect(self.open_qr_config_dialog)
        scan_menu.addAction(apply_alert_limits_action)

    def add_postprocessor_items(self, modules):
        for module_name, module in modules.items():
            action_text = getattr(module, 'description', module_name)
            checkbox_widget = self.create_checkbox_menu_item(
                action_text,
                self.postprocessors_menu,
                module.enabled,
                lambda checked, module=module: toggle_postprocessor(module)
            )
            self.postprocessors_menu.addAction(checkbox_widget)
            self.postprocessor_checkboxes[module_name] = checkbox_widget.defaultWidget().findChild(QCheckBox)

    def build_postprocessors_menu(self):
        """The menu, from whatever is loaded now.

        The modules that ship with the software and the ones the operator
        dropped into their own folder are ruled apart: the second kind can
        appear, break or vanish between launches, which is what makes a refresh
        and an empty-folder line worth saying.
        """
        menu = self.postprocessors_menu
        # Deletes the QWidgetActions — they are parented to the menu — and with
        # them the QCheckBoxes the old map pointed at.
        menu.clear()
        self.postprocessor_checkboxes = {}

        self.add_postprocessor_items(get_postprocessors(BUILTIN))

        menu.addSeparator()
        custom_postprocessors = get_postprocessors(CUSTOM)
        if custom_postprocessors:
            self.add_postprocessor_items(custom_postprocessors)
        else:
            no_custom_action = QAction(_('MENU_BAR_NO_CUSTOM_POSTPROCESSORS'), menu)
            no_custom_action.setEnabled(False)
            menu.addAction(no_custom_action)

        menu.addSeparator()
        menu.addAction(self.run_postprocessors_action)
        menu.addAction(self.refresh_postprocessors_action)
        menu.addAction(self.open_postprocessor_folder_action)

    def on_refresh_postprocessors(self):
        """Rescan the folders and rebuild the menu this was triggered from.

        Deferred by a zero timer on purpose: the action lives in the menu the
        rebuild clears, and clearing a menu inside the emission of one of its
        own actions deletes the object mid-signal.
        """
        if self.postprocess_manager.is_running():
            show_info_msgbox(
                _('MENU_BAR_POSTPROCESSORS_BUSY_TEXT'),
                _('MENU_BAR_POSTPROCESSORS_BUSY_TITLE'),
            )
            return
        QTimer.singleShot(0, self.reload_postprocessors)

    def reload_postprocessors(self):
        reload_postprocessors()
        # The manager holds module objects and the menu held lambdas bound to
        # them; both sets are stale the moment the files are re-imported.
        self.postprocess_manager.refresh_enabled_postprocessors()
        self.build_postprocessors_menu()

    def open_postprocessor_folder(self):
        """Open the folder custom postprocessors are read from, making it first.

        A menu item that opens nothing because the folder has never existed is
        a dead end — the point of it is to give the operator somewhere to drop
        a .py file. settings.IGNORE_FOLDERS already keeps 'postprocessors' out
        of the roll sweep, so an empty one is invisible everywhere else.
        """
        try:
            os.makedirs(user_postprocessors_path, exist_ok=True)
        except OSError as error:
            message = _("ERROR_MSGBOX_TEXT_DIRECTORY_NOT_FOUND").format(
                directory=user_postprocessors_path)
            show_error_msgbox(f"{message}\n\n{error}", _("ERROR_MSGBOX_TITLE"))
            return
        open_in_file_explorer(user_postprocessors_path)

    def create_checkbox_menu_item(self, label, parent_menu, checked, callback):
        """Helper method to create a persistent checkbox menu item."""
        widget = QWidget()
        layout = QVBoxLayout()
        # Reduce margins for better alignment
        theme_qt.pad(layout, 1, 0)
        theme_qt.gap(layout, 0)
        checkbox = QCheckBox(label)
        checkbox.setChecked(checked)
        # Connect checkbox state change to callback
        checkbox.stateChanged.connect(callback)
        layout.addWidget(checkbox)
        widget.setLayout(layout)

        widget_action = QWidgetAction(parent_menu)
        widget_action.setDefaultWidget(widget)

        return widget_action

    def on_show_all_com_ports_changed(self, checked):
        preferences.update_preferences({'show_all_com_ports': checked})
        self.serial_widget.view.model.applyFilter()

    def on_show_plot_toolbar_changed(self, checked):
        preferences.update_preferences({'show_plot_toolbar': checked})
        self.profile_widget.set_toolbar_visible(checked)

    def on_recalculate_mean_changed(self, checked):
        preferences.update_preferences({'recalculate_mean': checked})
        self.refresh_plot()

    def load_settings_file(self):
        dialog = QFileDialog(
            self,
            _('LOAD_SETTINGS_FILE_DIALOG_TITLE'),
            preferences.get_preferences_file_path(),
            _('LOAD_SETTINGS_FILE_DIALOG_FILTER'),
        )
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)

        if not dialog.exec():
            return

        selected_files = dialog.selectedFiles()
        if not selected_files:
            return

        self.load_settings_file_from_path(selected_files[0])

    def export_settings_file(self):
        dialog = QFileDialog(
            self,
            _('EXPORT_SETTINGS_FILE_DIALOG_TITLE'),
            preferences.get_preferences_file_path(),
            _('LOAD_SETTINGS_FILE_DIALOG_FILTER'),
        )
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setDefaultSuffix('json')

        if not dialog.exec():
            return

        selected_files = dialog.selectedFiles()
        if not selected_files:
            return

        path = selected_files[0]
        success = preferences.save_preferences_to_file(path)
        if not success:
            QMessageBox.critical(
                self,
                _('EXPORT_SETTINGS_FILE_ERROR_TITLE'),
                _('EXPORT_SETTINGS_FILE_ERROR_TEXT').format(path=path),
            )

    def load_settings_file_from_path(self, path):
        locale_before = preferences.locale
        result = preferences.load_preferences_from_file(path)

        if result.status in (
            preferences.LOAD_STATUS_LOADED,
            preferences.LOAD_STATUS_CREATED_DEFAULTS,
        ):
            if preferences.locale != locale_before:
                preferences.update_preferences({'locale': locale_before})
                QMessageBox.information(
                    self,
                    _('LOAD_SETTINGS_FILE_LOCALE_IGNORED_TITLE'),
                    _('LOAD_SETTINGS_FILE_LOCALE_IGNORED_TEXT'),
                )
            self.apply_loaded_preferences()
            return result

        if result.status in (
            preferences.LOAD_STATUS_EMPTY,
            preferences.LOAD_STATUS_INVALID,
        ):
            if not self.confirm_overwrite_settings_file(path, result.status, result.error):
                return result

            overwrite_result = preferences.overwrite_preferences_file_with_defaults(path)
            if overwrite_result.status == preferences.LOAD_STATUS_CREATED_DEFAULTS:
                self.apply_loaded_preferences()
                return overwrite_result

            self.show_settings_file_error(path, overwrite_result.error)
            return overwrite_result

        self.show_settings_file_error(path, result.error)
        return result

    def confirm_overwrite_settings_file(self, path, status, error=None):
        reason_key = (
            'LOAD_SETTINGS_FILE_EMPTY_TEXT'
            if status == preferences.LOAD_STATUS_EMPTY
            else 'LOAD_SETTINGS_FILE_INVALID_TEXT'
        )
        message = _("LOAD_SETTINGS_FILE_OVERWRITE_PROMPT").format(
            path=path,
            reason=_(reason_key),
        )
        if error:
            message = f"{message}\n\n{error}"

        reply = QMessageBox.question(
            self,
            _('LOAD_SETTINGS_FILE_OVERWRITE_TITLE'),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def show_settings_file_error(self, path, error=None):
        message = _("LOAD_SETTINGS_FILE_ERROR_TEXT").format(path=path)
        if error:
            message = f"{message}\n\n{error}"
        QMessageBox.critical(
            self,
            _('ERROR_MSGBOX_TITLE'),
            message,
        )

    def apply_loaded_preferences(self):
        self.postprocess_manager.refresh_enabled_postprocessors()
        self._sync_menu_checkbox_states()
        self.profile_widget.set_toolbar_visible(preferences.show_plot_toolbar)
        self.serial_widget.view.model.applyFilter()
        if self.settings_window:
            self.settings_window.close()
            self.settings_window = None
        self.refresh_plot()

    def _sync_menu_checkbox_states(self):
        checkbox_states = {
            'show_all_com_ports': preferences.show_all_com_ports,
            'show_plot_toolbar': preferences.show_plot_toolbar,
            'recalculate_mean': preferences.recalculate_mean,
        }
        for key, checked in checkbox_states.items():
            checkbox = self.view_menu_checkboxes.get(key)
            if checkbox is None:
                continue
            blocker = QSignalBlocker(checkbox)
            checkbox.setChecked(checked)
            del blocker

        for module_name, checkbox in self.postprocessor_checkboxes.items():
            blocker = QSignalBlocker(checkbox)
            checkbox.setChecked(module_name in preferences.enabled_postprocessors)
            del blocker

    def on_directory_selected(self, directory):
        # Validate that the directory path exists and is a directory
        if not directory or not os.path.exists(directory) or not os.path.isdir(directory):
            return

        directory_changed = store.selected_directory != directory
        self.directory_name = os.path.basename(directory)
        store.selected_directory = directory
        if directory_changed:
            store.selected_profile = None
        self.load_profiles(store.selected_directory)
        self.fileView.set_directory(store.selected_directory)
        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def on_statistics_directory_selected(self, directory):
        self.on_directory_selected(directory)
        self.statistics_analysis_widget.highlight_point(directory)

        blocker = QSignalBlocker(self.directory_view)
        self.directory_view.select_directory_by_path(directory)
        del blocker

    def load_profiles(self, dir_path):
        # Validate that the directory path exists and is a directory
        if not dir_path or not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            print(f"Invalid directory path provided to load_profiles: '{dir_path}'")
            return

        files = list_prof_files(store.selected_directory)
        profiles = [ Profile.fromfile(filename) for filename in files ]
        profiles = [ profile for profile in profiles if profile is not None ]
        store.profiles = profiles

        # Sort profiles using current sort criteria
        store.sort_profiles()

    def on_file_selected(self, file_path):
        filename = os.path.basename(file_path)
        store.selected_profile = filename
        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def on_directory_contents_changed(self):
        # Reload the selected directory and redraw plot. If the selected folder
        # was removed and no profile folders remain, leave the profile tab blank.
        if store.selected_directory and os.path.isdir(store.selected_directory):
            self.on_directory_selected(store.selected_directory)
            return

        if not self._root_has_profile_directories(store.root_directory):
            self._clear_profile_selection(store.root_directory)
            return

        self.directory_view.select_first_directory()

    def refresh_plot(self):
        if not store.selected_directory:
            return

        # Store which profiles are currently hidden
        # TODO: refactor this later, this was introduced only because flip feature was added
        hidden_names = set()
        for profile in store.profiles:
            if hasattr(profile, 'hidden') and profile.hidden:
                hidden_names.add(profile.name)

        # Reload profiles to apply new flip_profiles preference
        self.load_profiles(store.selected_directory)

        # Restore hidden state
        for profile in store.profiles:
            if profile.name in hidden_names:
                profile.hidden = True

        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def on_file_sort_changed(self, column_index, sort_order):
        """Handle file list sort changes and update the plot order accordingly."""
        store.sort_profiles(column_index, sort_order)
        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def on_root_directory_changed(self, directory):
        store.root_directory = directory
        if not self._path_is_within_directory(store.selected_directory, directory):
            root_has_profile_directories = self._root_has_profile_directories(directory)
            if not root_has_profile_directories:
                self.on_directory_selected(directory)
                return

            self._clear_profile_selection(
                directory,
                clear_plot=False,
            )

    def _clear_profile_selection(self, root_directory=None, clear_plot=True):
        store.selected_directory = None
        store.selected_profile = None
        store.profiles = []
        self.directory_name = None
        if root_directory and os.path.isdir(root_directory):
            self.fileView.set_directory(root_directory)
        if clear_plot:
            self.profile_widget.clear_plot_display()

    @staticmethod
    def _root_has_profile_directories(directory):
        if not directory or not os.path.isdir(directory):
            return False

        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir() and entry.name not in settings.IGNORE_FOLDERS:
                        return True
        except (OSError, PermissionError):
            return False

        return False

    @staticmethod
    def _path_is_within_directory(path, directory):
        if not path or not directory:
            return False

        try:
            path_abs = os.path.abspath(path)
            directory_abs = os.path.abspath(directory)
            common_path = os.path.commonpath([path_abs, directory_abs])
        except (OSError, ValueError):
            return False

        return os.path.normcase(common_path) == os.path.normcase(directory_abs)

    def open_settings_window(self):
        self.settings_window = SettingsWindow()
        self.settings_window.settings_updated.connect(self.refresh_plot)
        self.settings_window.general_settings_page.appearance_changed.connect(self.apply_appearance)
        self.settings_window.show()

    def _follow_system_appearance(self):
        """The desktop switched between light and dark.

        Only act while the *preference* is "system": a user who picked light
        explicitly keeps light when their machine turns the lights off.
        """
        if theme.requested() == theme.SYSTEM:
            self.apply_appearance(theme.SYSTEM)

    def apply_appearance(self, ui_theme):
        """Swap the theme at runtime — a night-shift toggle costs one call.

        The style sheet and the palette reach every widget on their own; what
        needs a nudge is everything drawn rather than styled: the baked icons
        inside the banners, and the two Matplotlib canvases.
        """
        theme.apply(QApplication.instance(), theme=ui_theme)
        # The stop mark is a pixmap baked in one theme's ink, so it is redrawn
        # rather than repolished.
        self._refresh_stop_icon()
        self.refresh_plot()
        self.statistics_analysis_widget.update_chart()
        for widget in self.findChildren(QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def open_log_window(self):
        self.log_window = LogWindow(store.log_manager)
        self.log_window.closed.connect(self.on_log_window_closed)
        self.log_window.show()

    def on_log_window_closed(self):
        self.log_window = None

    def open_qr_config_dialog(self):
        qr_dialog = QRConfigDialog(self)
        qr_dialog.show()

    def run_postprocessors_for_all_folders(self):
        # Get the base directory path
        base_dir = store.root_directory

        # Calculate the recent cutoff date if a cutoff time is defined
        if settings.POSTPROCESSORS_RECENT_CUTOFF_TIME_DAYS is not None:
            cutoff_date = datetime.now() - timedelta(days=settings.POSTPROCESSORS_RECENT_CUTOFF_TIME_DAYS)
            cutoff_timestamp = cutoff_date.timestamp()
        else:
            cutoff_timestamp = None

        folder_paths = []
        for folder in os.listdir(base_dir):
            folder_path = os.path.join(base_dir, folder)
            if os.path.isdir(folder_path):
                folder_mtime = os.path.getmtime(folder_path)
                folder_mod_date = datetime.fromtimestamp(folder_mtime)

                # Print folder modification date and comparison result
                print(f"Evaluating folder: {folder}")
                print(f" - Modification date: {folder_mod_date}")
                print(f" - Cutoff date: {datetime.fromtimestamp(cutoff_timestamp) if cutoff_timestamp else 'No cutoff'}")
                if os.path.basename(folder_path) in settings.IGNORE_FOLDERS:
                    print(" - Ignored")
                    continue

                if cutoff_timestamp is None or folder_mtime > cutoff_timestamp:
                    print(" - Included")
                    folder_paths.append(folder_path)
                else:
                    print(" - Excluded")


        print("Cutoff")
        print(cutoff_timestamp)
        print(folder_paths)

        # Run postprocessors on the filtered list of folders
        self.postprocess_manager.run_postprocessors(folder_paths)

    def run_postprocessors_for_folder(self, folder_path):
        """Run the enabled postprocessors over one roll folder.

        The menu's own item sweeps the working directory and drops anything
        older than the cutoff; this one was pointed at a folder, so it runs on
        that folder whatever its date.
        """
        if not folder_path or not os.path.isdir(folder_path):
            return
        if os.path.basename(folder_path) in settings.IGNORE_FOLDERS:
            return
        self.postprocess_manager.run_postprocessors([folder_path])

    def on_device_count_changed(self, count):
        self.set_status_message(_("SERIAL_SYNC_STATUS_BAR_TEXT").format(count=count))

    def on_postprocess_started(self, folder_count):
        self._postprocess_folder_count = folder_count
        message = _("POSTPROCESSORS_RUNNING_STATUS").format(count=folder_count)
        if self._sync_summary:
            # What the sync brought in stays on screen while its exports are
            # written, instead of being replaced by them a blink after it lands.
            message = f"{self._sync_summary} · {message}"
        self.start_activity(message, cancel=self.postprocess_manager.request_cancellation)

    def on_postprocess_progress(self, percent, folder_name, postprocessor_name):
        self.update_activity(
            percent,
            _("POSTPROCESSORS_RUNNING_ITEM_STATUS").format(
                folder=folder_name, postprocessor=postprocessor_name),
        )

    def on_postprocess_finished(self, result: PostprocessResult):
        """State what the run did, and interrupt only if something failed.

        A folder whose export failed without anyone noticing is a roll that
        silently has no report, which is worth a dialog. A clean run is not.
        """
        if self.postprocess_manager.was_cancelled:
            cancelled = _("POSTPROCESSORS_CANCELLED_STATUS")
            if self._sync_summary:
                cancelled = f"{self._sync_summary} · {cancelled}"
                self._sync_summary = None
            self.finish_activity(cancelled)
            return

        # The folders the run was over, not the ones that came back clean: a
        # folder where one export worked and another failed is still a folder
        # the run covered, and the failure count beside it is what says so.
        message = _("POSTPROCESSORS_FINISHED_STATUS").format(
            count=self._postprocess_folder_count or len(result.processed_folders))
        if result.failed_folders:
            message = f"{message} {_('POSTPROCESSORS_ERROR_TEXT').format(count=len(result.failed_folders))}"
        if self._sync_summary:
            message = f"{self._sync_summary} · {message}"
            self._sync_summary = None
        self.finish_activity(message)

        if result.failed_folders:
            folders = "\n".join(
                os.path.basename(path.rstrip(os.sep)) for path in sorted(result.failed_folders)
            )
            QMessageBox.warning(
                self,
                _("POSTPROCESSORS_FAILED_TITLE"),
                f"{_('POSTPROCESSORS_FAILED_TEXT').format(count=len(result.failed_folders))}\n\n{folders}",
            )

    def on_file_transfer_started(self):
        self.start_activity(
            _("SYNC_CHECKING_TEXT"),
            cancel=self.file_transfer_manager.cancel_transfer,
        )

    def on_sync_batch_started(self, port, file_count, byte_count):
        """The device has said what it is about to send.

        Worth stating before the first file lands: how many and how much is
        what tells the operator whether this is a five-second sync or one to
        walk away from.
        """
        if file_count <= 0:
            return
        self._transfer_total_files = file_count
        self._transfer_file_number = 0
        self.update_activity(
            0,
            _("SYNC_BATCH_STATUS").format(count=file_count, size=format_bytes(byte_count)),
        )

    def on_transfer_file_started(self, *_args):
        """A new file started arriving; the model row is what says so."""
        model = self.file_transfer_manager.model
        latest = model.getLatestItem()
        if not latest:
            return
        total = model.getTotalFileCount()
        self._transfer_file_number = total - latest.files_remaining + 1
        self._transfer_total_files = total
        self._transfer_file_name = latest.filename
        self.update_activity(
            self._transfer_percent(0.0),
            _("SYNC_RECEIVING_STATUS").format(
                number=self._transfer_file_number, total=total, filename=latest.filename),
        )

    def on_transfer_byte_progress(self, transferred, total_bytes):
        if not getattr(self, "_transfer_total_files", 0):
            return
        fraction = (transferred / total_bytes) if total_bytes else 0.0
        self.update_activity(
            self._transfer_percent(fraction),
            _("SYNC_RECEIVING_BYTES_STATUS").format(
                number=self._transfer_file_number,
                total=self._transfer_total_files,
                filename=self._transfer_file_name,
                done=format_bytes(transferred),
                size=format_bytes(total_bytes),
            ),
        )

    def _transfer_percent(self, fraction_of_current):
        """Whole-transfer percent, counting the file in flight as a fraction."""
        total = getattr(self, "_transfer_total_files", 0)
        if not total:
            return 0
        completed = self._transfer_file_number - 1 + fraction_of_current
        return int((completed / total) * 100)

    def on_file_transfer_finished(self, folder_paths: list[str]):
        received_count = self.file_transfer_manager.model.rowCount()
        self._transfer_total_files = 0
        removed_count = self.file_transfer_manager.last_deleted_count
        removed_text = (
            _("DEVICE_FILES_REMOVED").format(count=removed_count)
            if removed_count
            else ""
        )
        if folder_paths:
            # The summary counts both what arrived and where it went: "12
            # profiles" and "3 rolls" are the two numbers an operator checks
            # against what they expected the device to be carrying.
            summary = _("SYNC_FINISHED_STATUS").format(
                files=received_count, folders=len(folder_paths))
            summary = f"{summary} {removed_text}".strip()
            # Postprocessing starts on the next line and takes the status bar
            # over, so the sync's own summary would be on screen for a blink.
            # It is held and read out again with theirs, once the whole
            # sequence the operator pressed one button for is actually done.
            self._sync_summary = summary
            self.finish_activity(summary)
        elif self.file_transfer_manager.last_transfer_outcome == "ok":
            self.finish_activity(removed_text)
            if not self.file_transfer_manager.last_transfer_was_auto:
                QMessageBox.information(
                    self,
                    _("SYNC_UP_TO_DATE_TITLE"),
                    f"{_('SYNC_UP_TO_DATE_TEXT')} {removed_text}".strip(),
                )
        elif self.status_message() == _("SYNC_CHECKING_TEXT"):
            # Cancel/error before anything moved: the error handlers own
            # the message, just drop the stale "checking" text.
            self.finish_activity()
        else:
            self.finish_activity(self.status_message())
        if not folder_paths:
            return
        self.directory_view.refresh_directory_dates(folder_paths)
        self.postprocess_manager.run_postprocessors(folder_paths)
        self.on_directory_contents_changed()

    def on_transfer_error(self, message):
        self.finish_activity(message)
        # transferError also carries an is_auto flag, which the status
        # bar does not need: both cases want the message here, and a
        # manual failure additionally gets a popup from the transfer
        # manager.

    def on_connection_lost(self, port, reason):
        if reason == "busy":
            self.set_status_message(_("DEVICE_BUSY_STATUS"))
        elif reason in ("unplugged", "dead"):
            self.set_status_message(
                _("DEVICE_DISCONNECTED_STATUS").format(
                    device=self.device_connection_manager.device_label(port)
                )
            )

    def on_sync_list_warnings(self, port, skipped_count):
        self.set_status_message(
            _("SYNC_LIST_SKIPPED_WARNING").format(count=skipped_count)
        )

    def close_child_windows(self):
        if self.settings_window:
            self.settings_window.close()
            self.settings_window = None
        if self.log_window:
            self.log_window.close()
            self.log_window = None

    def stop_background_workers(self, timeout_ms=5000):
        """
        Stops the device scan and any file transfer, and waits for both threads.

        Qt aborts the process if a QThread is destroyed while its OS thread is
        still running, so closing the window during a scan or a sync has to bring
        those threads down first.
        """
        serial_widget = self.serial_widget
        scanner_stopped = serial_widget.scanner.stop(timeout_ms)

        transfer_manager = serial_widget.transferManager
        transfer_manager.cancel_transfer()
        transfer_stopped = transfer_manager.wait_for_transfer(timeout_ms)

        postprocess_stopped = self.postprocess_manager.stop_postprocessing(timeout_ms)

        if not scanner_stopped:
            print("Timed out waiting for the device scan to stop.")
        if not transfer_stopped:
            print("Timed out waiting for the file transfer to stop.")
        if not postprocess_stopped:
            print("Timed out waiting for postprocessing to stop.")
        return scanner_stopped and transfer_stopped and postprocess_stopped

    def closeEvent(self, event):
        self.file_transfer_manager.cancel_transfer()
        self.device_connection_manager.shutdown_all()
        self.serial_widget.scanner.stop()
        self.close_child_windows()
        self.stop_background_workers()
        event.accept()
