from PySide6.QtWidgets import QVBoxLayout, QFrame
from gui.widgets.DirectoryView import DirectoryView
from gui.widgets.serialports import SerialWidget

class Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(400)  # Initial width of the sidebar

        self.directoryView = DirectoryView()
        self.serialView = SerialWidget()

        # Layout for the sidebar's content
        self.layout = QVBoxLayout(self)
        # Add any widgets you want in the sidebar
        self.layout.addWidget(self.serialView)
        self.layout.addWidget(self.directoryView)