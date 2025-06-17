from PySide6.QtWidgets import QVBoxLayout, QFrame

class Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLayout(QVBoxLayout(self))

    def addWidget(self, widget):
        self.layout().addWidget(widget)