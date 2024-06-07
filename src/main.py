
# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.


import sys
import struct
from PySide6.QtCore import Qt, QDir
from PySide6.QtWidgets import QApplication, QMainWindow, QGridLayout, QWidget
from PySide6.QtGui import QAction
import numpy as np
from utils.file_utils import list_prof_files, read_prof_file
import os

# Assuming Sidebar, Chart, and FileView are implemented elsewhere
from gui.widgets.sidebar import Sidebar
from gui.widgets.FileView import FileView
from gui.widgets.chart import Chart
import settings

from gui.settings import SettingsWindow

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

        self.sidebar.directoryView.treeView.selectionModel().currentChanged.connect(self.on_directory_selected)
        self.sidebar.directoryView.treeView.rootIndexChanged.connect(self.on_root_index_changed)
        self.sidebar.directoryView.treeView.rootIndexChanged.emit()

        centralWidgetLayout.addWidget(self.sidebar, 0, 0, 2, 1)  # Sidebar spans 2 rows
        centralWidgetLayout.addWidget(self.chart, 0, 1)  # Chart at row 0, column 1
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

    def init_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('File')
        settings_action = QAction('Settings', self)
        settings_action.triggered.connect(self.open_settings_window)
        file_menu.addAction(settings_action)

        menu_bar.addMenu('View')


    def on_directory_selected(self, current, previous):
        path = self.sidebar.directoryView.model.filePath(current)
        self.directory_name = os.path.basename(path)
        print(path)
        self.fileView.set_directory(path)
        files = list_prof_files(path)
        self.profiles = [read_prof_file(fn) for fn in files]
        self.chart.update_plot(self.profiles, self.directory_name)
        self.fileView.view.clearSelection()

        for postp_f in settings.POSTPROCESSORS:
            postp_f(path)

    def on_file_selected(self, file_path):
        filename = os.path.basename(file_path)
        self.chart.update_plot(self.profiles, self.directory_name, selected=filename)

    def on_root_index_changed(self):
        index = self.sidebar.directoryView.treeView.rootIndex()
        path = self.sidebar.directoryView.model.filePath(index)
        self.sidebar.serialView.syncFolder = path

    def open_settings_window(self):
        self.settings_window = SettingsWindow()
        self.settings_window.settings_updated.connect(self.refresh)
        self.settings_window.show()

    def refresh(self):
        self.chart.update_plot(self.profiles, self.directory_name)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    main()
