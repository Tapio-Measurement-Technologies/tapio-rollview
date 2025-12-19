# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.


from PySide6.QtWidgets import QMainWindow, QStatusBar, QWidget, QCheckBox, QVBoxLayout, QWidgetAction, QSplitter, QTabWidget, QProgressBar
from PySide6.QtGui import QAction
from PySide6.QtCore import QDir, Qt

from utils.file_utils import list_prof_files
from utils.postprocess import toggle_postprocessor, PostprocessManager, get_postprocessors, PostprocessResult
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
from gui.widgets.serialports import SerialWidget
from gui.widgets.DirectoryView import DirectoryView
from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget
from gui.settings import SettingsWindow
from utils.translation import _

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"Tapio RollView {store.app_version}")
        self.resize(1000, 600)

        self.file_transfer_manager = FileTransferManager()
        self.postprocess_manager = PostprocessManager()
        self.log_window = None
        self.settings_window = None

        self.serial_widget = SerialWidget(self.file_transfer_manager)
        self.directory_view = DirectoryView()
        self.sidebar = Sidebar()
        self.sidebar.addWidget(self.serial_widget, 200)
        self.sidebar.addWidget(self.directory_view)

        self.tab_view = QTabWidget()
        self.statistics_analysis_widget = StatisticsAnalysisWidget()
        self.statistics_analysis_widget.directory_selected.connect(self.on_directory_selected)
        self.profile_widget = ProfileWidget()
        self.tab_view.addTab(self.profile_widget, _("TAB_TITLE_PROFILES"))
        self.tab_view.addTab(self.statistics_analysis_widget, _("TAB_TITLE_STATISTICS"))
        self.tab_view.currentChanged.connect(self.statistics_analysis_widget.update)

        self.fileView = FileView()
        self.fileView.file_selected.connect(self.on_file_selected)
        self.fileView.profile_state_changed.connect(self.refresh_plot)

        self.directory_view.directory_selected.connect(self.on_directory_selected)
        self.directory_view.directory_selected.connect(self.statistics_analysis_widget.highlight_point)
        self.directory_view.root_directory_changed.connect(self.on_root_directory_changed)
        self.directory_view.root_directory_changed.connect(self.statistics_analysis_widget.update)
        self.directory_view.directory_contents_changed.connect(self.on_directory_contents_changed)
        self.directory_view.directory_contents_changed.connect(self.statistics_analysis_widget.update)

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
        ver_splitter.setSizes([200, 200])

        hor_splitter = QSplitter(Qt.Orientation.Horizontal)
        hor_splitter.addWidget(self.sidebar)
        hor_splitter.addWidget(ver_splitter)
        hor_splitter.setStretchFactor(0, 0)
        hor_splitter.setStretchFactor(1, 1)
        hor_splitter.setSizes([400, 600])
        hor_splitter.setCollapsible(0, False)
        hor_splitter.setCollapsible(1, False)

        self.status_bar = QStatusBar()
        self.status_bar.setFixedHeight(30)
        self.setStatusBar(self.status_bar)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.scan_progress_bar)

        self.setCentralWidget(hor_splitter)
        self.init_menu()

        # Scan devices on startup
        self.serial_widget.scan_devices()
        self.serial_widget.device_count_changed.connect(self.on_device_count_changed)
        self.serial_widget.scan_progress.connect(self.on_scan_progress)
        self.serial_widget.scan_finished.connect(self.on_scan_finished)

        # Run postprocessors when file transfer is finished
        self.file_transfer_manager.transferFinished.connect(self.on_file_transfer_finished)

        self.postprocess_manager.postprocess_finished.connect(self.on_postprocess_finished)

    def on_scan_progress(self, value, text):
        self.scan_progress_bar.setVisible(True)
        self.scan_progress_bar.setValue(value)
        self.status_bar.showMessage(text)

    def on_scan_finished(self):
        self.scan_progress_bar.setVisible(False)
        self.status_bar.clearMessage()

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

        view_menu = menu_bar.addMenu(_('MENU_BAR_VIEW'))
        show_all_com_ports_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_SHOW_ALL_COM_PORTS'),
            # 'Show all COM ports'
            view_menu,
            preferences.show_all_com_ports,
            self.on_show_all_com_ports_changed
        )
        show_plot_toolbar_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_SHOW_PLOT_TOOLBAR'),
            # 'Show toolbar',
            view_menu,
            preferences.show_plot_toolbar,
            self.on_show_plot_toolbar_changed
        )
        recalculate_mean_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_RECALCULATE_MEAN'),
            # 'Recalculate mean on profile show/hide',
            view_menu,
            preferences.recalculate_mean,
            self.on_recalculate_mean_changed
        )

        log_window_action = QAction("Application logs", self)
        log_window_action.triggered.connect(self.open_log_window)

        view_menu.addAction(show_all_com_ports_checkbox)
        view_menu.addAction(show_plot_toolbar_checkbox)
        view_menu.addAction(recalculate_mean_checkbox)
        view_menu.addAction(log_window_action)

        postprocessors_menu = menu_bar.addMenu(_('MENU_BAR_POSTPROCESSORS'))

        # Add 'Run after sync' heading using QLabel for better styling
        # run_after_sync_label = QLabel('Run after sync')
        # run_after_sync_label.setFont(QFont('Arial', 10, QFont.Weight.Normal))  # Make the text bold
        # run_after_sync_label.setMargin(5)
        # run_after_sync_label_action = QWidgetAction(self)
        # run_after_sync_label_action.setDefaultWidget(run_after_sync_label)
        # postprocessors_menu.addAction(run_after_sync_label_action)

        for module_name, module in get_postprocessors().items():
            action_text = getattr(module, 'description', module_name)
            checkbox_widget = self.create_checkbox_menu_item(
                action_text,
                postprocessors_menu,
                module.enabled,
                lambda checked, module=module: toggle_postprocessor(module)
            )
            postprocessors_menu.addAction(checkbox_widget)

        # Add the 'Run postprocessors' item
        run_postprocessors_action = QAction(_('MENU_BAR_RUN_POSTPROCESSORS'), self)
        run_postprocessors_action.triggered.connect(
            self.run_postprocessors_for_all_folders)
        # run_postprocessors_action.triggered.connect(self.run_postprocessors)  # Method to run postprocessors
        postprocessors_menu.addAction(run_postprocessors_action)

    def create_checkbox_menu_item(self, label, parent_menu, checked, callback):
        """Helper method to create a persistent checkbox menu item."""
        widget = QWidget()
        layout = QVBoxLayout()
        # Reduce margins for better alignment
        layout.setContentsMargins(5, 0, 5, 0)
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
        preferences.update_show_all_com_ports(checked)
        self.serial_widget.view.model.applyFilter()

    def on_show_plot_toolbar_changed(self, checked):
        preferences.update_show_plot_toolbar(checked)
        self.profile_widget.set_toolbar_visible(checked)

    def on_recalculate_mean_changed(self, checked):
        preferences.update_recalculate_mean(checked)
        self.refresh_plot()

    def on_directory_selected(self, directory):
        # Validate that the directory path exists and is a directory
        if not directory or not os.path.exists(directory) or not os.path.isdir(directory):
            print(f"Invalid directory path provided to on_directory_selected: '{directory}'")
            return

        self.directory_name = os.path.basename(directory)
        store.selected_directory = directory
        self.load_profiles(store.selected_directory)
        self.fileView.set_directory(store.selected_directory)
        self.directory_view.select_directory_by_path(store.selected_directory)
        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def load_profiles(self, dir_path):
        # Validate that the directory path exists and is a directory
        if not dir_path or not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            print(f"Invalid directory path provided to load_profiles: '{dir_path}'")
            return

        files = list_prof_files(store.selected_directory)
        profiles = [ Profile.fromfile(filename) for filename in files ]
        profiles = [ profile for profile in profiles if profile is not None ]
        store.profiles = profiles

    def on_file_selected(self, file_path):
        filename = os.path.basename(file_path)
        self.profile_widget.update_plot(
            store.profiles, self.directory_name, selected=filename)

    def on_directory_contents_changed(self):
        # Reload the selected directory and redraw plot
        self.on_directory_selected(store.selected_directory)

    def refresh_plot(self):
        self.load_profiles(store.selected_directory)
        self.profile_widget.update_plot(store.profiles, self.directory_name)

    def on_root_directory_changed(self, directory):
        store.root_directory = directory

    def open_settings_window(self):
        self.settings_window = SettingsWindow()
        self.settings_window.settings_updated.connect(self.refresh_plot)
        self.settings_window.show()

    def open_log_window(self):
        self.log_window = LogWindow(store.log_manager)
        self.log_window.closed.connect(self.on_log_window_closed)
        self.log_window.show()

    def on_log_window_closed(self):
        self.log_window = None

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

    def on_device_count_changed(self, count):
        self.status_bar.showMessage(f"{_('SERIAL_SYNC_STATUS_BAR_TEXT_1')} {count} {_('SERIAL_SYNC_STATUS_BAR_TEXT_2')}")

    def on_postprocess_finished(self, result: PostprocessResult):
        message = _("POSTPROCESSORS_FINISHED_TEXT")
        if result.failed_folders:
            message += f" {_('POSTPROCESSORS_ERROR_TEXT_1')} {len(result.failed_folders)} {_('POSTPROCESSORS_ERROR_TEXT_2')}"
        self.status_bar.showMessage(message)

    def on_file_transfer_finished(self, folder_paths: list[str]):
        self.status_bar.showMessage(f"{_('FILE_TRANSFER_FINISHED')}")
        self.postprocess_manager.run_postprocessors(folder_paths)
        self.on_directory_contents_changed()

    def close_child_windows(self):
        if self.settings_window:
            self.settings_window.close()
            self.settings_window = None
        if self.log_window:
            self.log_window.close()
            self.log_window = None

    def closeEvent(self, event):
        self.close_child_windows()
        event.accept()