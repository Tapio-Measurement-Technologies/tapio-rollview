from PySide6.QtWidgets import QListView, QWidget, QPushButton, QVBoxLayout, QLabel, QApplication
from PySide6.QtCore import Qt, QThread
from models.SerialDevice import SerialDeviceModel
from gui.filetransferdialog import FileTransferDialog
from utils.serial import FileTransferManager
from utils.scan_devices import USBDeviceScanWorker, BluetoothDeviceScanWorker

class SerialPortView(QListView):

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the model
        self.model = SerialDeviceModel()
        self.setModel(self.model)

        # Create and start the worker threads for device scanning
        self.start_usb_scan_thread()
        self.start_bt_scan_thread()

    def start_usb_scan_thread(self):
        # Create a QThread object
        self.usb_thread = QThread()
        # Create a worker object
        self.usb_worker = USBDeviceScanWorker()
        # Move the worker to the thread
        self.usb_worker.moveToThread(self.usb_thread)
        # Connect signals and slots
        self.usb_thread.started.connect(self.usb_worker.run)
        self.usb_worker.usb_devices_scanned.connect(self.on_usb_devices_scanned)
        # Start the thread
        self.usb_thread.start()

    def start_bt_scan_thread(self):
        # Create a QThread object
        self.bt_thread = QThread()
        # Create a worker object
        self.bt_worker = BluetoothDeviceScanWorker()
        # Move the worker to the thread
        self.bt_worker.moveToThread(self.bt_thread)
        # Connect signals and slots
        self.bt_thread.started.connect(self.bt_worker.run)
        self.bt_worker.bt_devices_scanned.connect(self.on_bt_devices_scanned)
        # Start the thread
        self.bt_thread.start()

    def on_usb_devices_scanned(self, devices):
        # This will be called in the main thread to update only USB devices
        self.model.removeItemsByType('USB')
        for device in devices:
            self.model.addItem(device)

    def on_bt_devices_scanned(self, devices):
        # This will be called in the main thread to update only Bluetooth devices
        self.model.removeItemsByType('BT')
        for device in devices:
            self.model.addItem(device)

    def closeEvent(self, event):
        # Override the close event to stop the threads
        self.stop_worker_threads()
        super().closeEvent(event)

    def stop_worker_threads(self):
        # Stop the USB worker thread safely
        self.usb_worker.stop()  # Stop the worker loop
        self.usb_thread.quit()  # Quit the thread loop
        self.usb_thread.wait()  # Wait for the thread to finish
        if self.usb_thread.isRunning():
            self.usb_thread.terminate()  # Force terminate if still running

        # Stop the Bluetooth worker thread safely
        self.bt_worker.stop()  # Stop the worker loop
        self.bt_thread.quit()  # Quit the thread loop
        self.bt_thread.wait()  # Wait for the thread to finish
        if self.bt_thread.isRunning():
            self.bt_thread.terminate()  # Force terminate if still running

    def select_item(self, row):
        index = self.model.index(row, 0)  # Assumes a single column
        if index.isValid():
            # Set selection
            self.setCurrentIndex(index)
            # Optionally ensure the item is visible
            self.scrollTo(index)

    def restore_selection(self, selected_port_data):
        index = self.model.getSelectedDeviceIndex()
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

        # Connect application's aboutToQuit signal to ensure thread cleanup
        QApplication.instance().aboutToQuit.connect(self.cleanup)

        self.view.selectionModel().currentChanged.connect(self.on_device_selected)

    def on_device_selected(self, current, previous):
        selected_device = current.data(Qt.ItemDataRole.UserRole)
        self.view.model.selectDevice(selected_device)
        self.syncButton.setEnabled(current.isValid())

    def sync_data(self):
        self.transferDialog.show()
        device = self.view.model.getSelectedDevice()
        if device:
            self.transferManager.start_transfer(device, self.syncFolder, self.transferDialog.on_complete)

    def cleanup(self):
        # Ensure the worker threads are stopped properly when the application is quitting
        self.view.stop_worker_threads()
