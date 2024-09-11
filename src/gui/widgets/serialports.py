from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer, Qt, QThread, Signal, QObject
import serial.tools.list_ports
import serial
import json
from settings import SERIAL_SCAN_INTERVAL
from models.SerialPort import SerialPortModel, SerialPortItem
from gui.filetransferdialog import FileTransferDialog
from utils.serial import FileTransferManager
from utils.time_sync import send_timestamp
import settings

class SerialPortScanner(QObject):
    """
    Worker class to scan serial ports in a separate thread.
    """
    ports_scanned = Signal(list)  # Signal to emit the list of valid ports

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self.timer = QTimer(self)
        self.timer.setInterval(SERIAL_SCAN_INTERVAL)
        self.timer.timeout.connect(self.scan_ports)

    def stop(self):
        self._running = False
        if self.timer.isActive():
           self.timer.stop()

    def run(self):
        self.timer = QTimer(self)
        self.timer.setInterval(SERIAL_SCAN_INTERVAL)
        self.timer.timeout.connect(self.scan_ports)
        self._running = True
        self.timer.start()

    def scan_ports(self):
        print("Starting port scan...")
        """
        Scans for available serial ports, sends a query to each, and checks for a specific JSON response.
        """
        ports = serial.tools.list_ports.comports()
        valid_ports = []

        for port_info in ports:
            if not self._running:
                break
            try:
                port = serial.Serial(port_info.device, settings.SERIAL_PORT_TIMEOUT, write_timeout=settings.SERIAL_PORT_TIMEOUT)  # Open the serial port
                port.write(b"RQP+DEVICEINFO?\n")  # Send the query
                response = port.readline().decode('utf-8').strip()  # Read the response
                send_timestamp(port)
                port.close()

                # Check if the response is a valid JSON with the expected keys
                try:
                    response_data = json.loads(response)
                    if 'deviceName' in response_data and 'serialNumber' in response_data:
                        # If valid, create a SerialPortItem with the new details
                        port_info.description = response_data['deviceName']
                        port_info.serial_number = response_data['serialNumber']
                        valid_ports.append(SerialPortItem(port_info))
                except json.JSONDecodeError:
                    # Ignore invalid JSON responses
                    pass

            except (serial.SerialException, OSError):
                # Ignore ports that cannot be opened or cause an error
                continue

        self.ports_scanned.emit(valid_ports)
        print(f"Found {len(valid_ports)} ports: {valid_ports}")


class SerialPortView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the model
        self.model = SerialPortModel()
        self.setModel(self.model)

        # Set up the scanner thread
        self.thread = QThread()
        self.scanner = SerialPortScanner()
        self.scanner.moveToThread(self.thread)
        self.scanner.ports_scanned.connect(self.update_com_ports)
        self.thread.started.connect(self.scanner.run)

    def start_scan(self):
        if not self.thread.isRunning():
            self.thread.start()

    def stop_scan(self):
        if self.thread.isRunning():
            self.scanner.stop()
            self.thread.quit()
            self.thread.wait()

    def update_com_ports(self, valid_ports):
        # Clear existing items
        self.model.removeItems()
        # Add valid ports to the model
        for port in valid_ports:
            self.model.addItem(port)

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
        layout.addWidget(self.syncButton)

        self.view.selectionModel().currentChanged.connect(self.on_port_selected)

        self.view.start_scan()

    def on_port_selected(self, current, previous):
        selected_port = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectPort(selected_port)
        self.syncButton.setEnabled(current.isValid())

    def sync_data(self):
        self.view.stop_scan()
        self.transferDialog.show()
        port = self.view.model.getSelectedPort().port.device
        if port:
            self.transferManager.start_transfer(port, self.syncFolder, self.on_complete)

    def on_complete(self):
        self.view.start_scan()
        self.transferDialog.on_complete()
        self.view.scanner._running = True

    def closeEvent(self, event):
        # Stop the scanner thread when the widget is closed
        self.view.stop_scan()
        super().closeEvent(event)
