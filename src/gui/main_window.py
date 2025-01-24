
# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.


from PySide6.QtWidgets import QMainWindow, QGridLayout, QWidget, QCheckBox, QVBoxLayout, QWidgetAction, QLabel
from PySide6.QtGui import QAction
from PySide6.QtCore import QDir, Qt

from utils.file_utils import list_prof_files
from utils.postprocess import toggle_postprocessor, run_postprocessors, get_postprocessors
from utils import preferences
import os
from datetime import datetime, timedelta


# Assuming Sidebar, Chart, and FileView are implemented elsewhere
from gui.widgets.sidebar import Sidebar
from gui.widgets.FileView import FileView
from gui.widgets.chart import Chart
from models.Profile import Profile
import settings
import store

from gui.settings import SettingsWindow
from gettext import gettext as _


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Tapio RollView")
        self.resize(900, 600)

        centralWidgetLayout = QGridLayout()
        centralWidget = QWidget()
        centralWidget.setLayout(centralWidgetLayout)

        self.sidebar = Sidebar()
        self.chart = Chart()
        self.fileView = FileView()
        self.fileView.file_selected.connect(self.on_file_selected)
        self.fileView.profile_state_changed.connect(self.refresh_plot)

        self.sidebar.directoryView.directory_selected.connect(self.on_directory_selected)
        self.sidebar.directoryView.root_directory_changed.connect(
            self.on_root_directory_changed)
        self.sidebar.directoryView.directory_contents_changed.connect(
            self.on_directory_contents_changed
        )

        # Attempt to create default root dir if it does not exist
        if QDir().mkpath(store.root_directory):
            self.sidebar.directoryView.change_root_directory(store.root_directory)
        else:
            current_path = QDir.currentPath()
            print(f"Failed to create default roll directory to {store.root_directory}!")
            print(f"Defaulting to {current_path}")
            self.sidebar.directoryView.change_root_directory(current_path)

        centralWidgetLayout.addWidget(
            self.sidebar, 0, 0, 2, 1)  # Sidebar spans 2 rows
        centralWidgetLayout.addWidget(
            self.chart, 0, 1)  # Chart at row 0, column 1
        # FileView at row 1, column 1
        centralWidgetLayout.addWidget(self.fileView, 1, 1)
        centralWidgetLayout.setContentsMargins(0, 0, 0, 0)

        # Set column and row stretch factors to make the chart and file view expand
        centralWidgetLayout.setColumnStretch(0, 1)  # Sidebar
        centralWidgetLayout.setColumnStretch(1, 3)  # Chart and FileView
        centralWidgetLayout.setRowStretch(0, 2)  # Chart
        centralWidgetLayout.setRowStretch(1, 1)  # FileView

        self.setCentralWidget(centralWidget)
        self.init_menu()

        # Scan devices on startup
        self.sidebar.serialView.scan_devices()

    def keyPressEvent(self, event):
        """Forward key press events to the chart."""
        if self.chart:
            self.chart.keyPressEvent(event)
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
        recalculate_mean_checkbox = self.create_checkbox_menu_item(
            _('MENU_BAR_RECALCULATE_MEAN'),
            # 'Recalculate mean on profile show/hide',
            view_menu,
            preferences.recalculate_mean,
            self.on_recalculate_mean_changed
        )
        view_menu.addAction(show_all_com_ports_checkbox)
        view_menu.addAction(recalculate_mean_checkbox)

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
        self.sidebar.serialView.view.model.applyFilter()

    def on_recalculate_mean_changed(self, checked):
        preferences.update_recalculate_mean(checked)
        self.refresh_plot()

    def on_directory_selected(self, directory):
        self.directory_name = os.path.basename(directory)
        store.selected_directory = directory
        print(directory)
        self.load_profiles(store.selected_directory)
        self.chart.update_plot(store.profiles, self.directory_name)

    def load_profiles(self, dir_path = None):
        if not dir_path:
            dir_path = store.selected_directory
        files = list_prof_files(store.selected_directory)
        profiles = [ Profile.fromfile(filename) for filename in files ]
        profiles = [ profile for profile in profiles if profile is not None ]
        store.profiles = profiles
        self.fileView.set_directory(dir_path)

    def on_file_selected(self, file_path):
        filename = os.path.basename(file_path)
        self.chart.update_plot(
            store.profiles, self.directory_name, selected=filename)

    def on_directory_contents_changed(self):
        # Reload the selected directory and redraw plot
        self.on_directory_selected(store.selected_directory)

    def refresh_plot(self):
        self.chart.update_plot(store.profiles, self.directory_name)

    def on_root_directory_changed(self, directory):
        store.root_directory = directory

    def open_settings_window(self):
        self.settings_window = SettingsWindow()
        self.settings_window.settings_updated.connect(self.refresh_plot)
        self.settings_window.show()

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
                if cutoff_timestamp is None or folder_mtime > cutoff_timestamp:
                    print(" - Included")
                    folder_paths.append(folder_path)
                else:
                    print(" - Excluded")


        print("Cutoff")
        print(cutoff_timestamp)
        print(folder_paths)

        # Run postprocessors on the filtered list of folders
        run_postprocessors(folder_paths)
