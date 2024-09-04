from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer, Qt
import serial.tools.list_ports
from settings import SERIAL_SCAN_INTERVAL
from models.SerialPort import SerialPortModel, SerialPortItem
from gui.filetransferdialog import FileTransferDialog
from utils.serial import FileTransferManager


class SerialPortView(QListView):

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the model
        self.model = SerialPortModel()
        self.setModel(self.model)

        # Populate the tree view with COM port data
        self.populate_com_ports()

    def populate_com_ports(self):
        # Clear existing items
        self.model.removeItems()

        # List available COM ports and add them to the model
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.model.addItem(SerialPortItem(port))

        self.restore_selection()

    def select_item(self, row):
        index = self.model.index(row, 0)  # Assumes a single column
        if index.isValid():
            # Set selection
            self.setCurrentIndex(index)
            # Optionally ensure the item is visible
            self.scrollTo(index)

    def restore_selection(self):
        index = self.model.getSelectedPortIndex()
        self.select_item(index)


class SerialWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMaximumHeight(200)
        # Create the COM Ports TreeView
        self.view = SerialPortView()

        self.label = QLabel("Devices")

        # Create the reload button
        # self.reloadButton = QPushButton("Scan devices")
        # self.reloadButton.clicked.connect(self.view.populate_com_ports)

        self.syncButton = QPushButton("Sync data")
        self.syncButton.clicked.connect(self.sync_data)
        self.syncButton.setEnabled(False)

        self.transferManager = FileTransferManager()
        self.transferDialog = FileTransferDialog(self.transferManager)

        self.syncFolder = None

        # Arrange the tree view and button in a vertical layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.view)
        # layout.addWidget(self.reloadButton)
        layout.addWidget(self.syncButton)

        self.timer = QTimer(self)
        self.timer.setInterval(SERIAL_SCAN_INTERVAL)
        self.timer.timeout.connect(self.view.populate_com_ports)
        self.timer.start()

        self.view.selectionModel().currentChanged.connect(self.on_port_selected)

    def on_port_selected(self, current, previous):
        selected_port = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectPort(selected_port)
        self.syncButton.setEnabled(current.isValid())

    def sync_data(self):
        self.transferDialog.show()
        port = self.view.model.getSelectedPort().port.device
        if port:
            self.transferManager.start_transfer(port, self.syncFolder, self.transferDialog.on_complete)
