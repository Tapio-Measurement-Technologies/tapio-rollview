from PySide6.QtCore import Signal, QObject
import serial.tools.list_ports
from settings import SERIAL_SCAN_INTERVAL
from models.SerialDevice import SerialDevice
import bluetooth as bluez
import time

class USBDeviceScanWorker(QObject):
    # Signal to emit when USB devices are scanned
    usb_devices_scanned = Signal(list)

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        # This method will run continuously in a separate thread
        while self.running:
            devices = []

            # List available COM ports and add them to the devices list
            ports = serial.tools.list_ports.comports()
            ports = [port for port in ports if 'tapio' in port.description.lower()]
            for port in ports:
                device = {
                    'name': port.description,
                    'port': port.device,
                    'type': 'USB'
                }
                devices.append(SerialDevice(device))

            # Emit the signal with the list of USB devices
            self.usb_devices_scanned.emit(devices)

            # Sleep for a specified interval before the next scan
            time.sleep(SERIAL_SCAN_INTERVAL / 1000.0)

    def stop(self):
        # Stop the scanning loop
        self.running = False

class BluetoothDeviceScanWorker(QObject):
    # Signal to emit when Bluetooth devices are scanned
    bt_devices_scanned = Signal(list)

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        # This method will run continuously in a separate thread
        while self.running:
            devices = []

            # Scan for Bluetooth devices
            try:
                services = bluez.find_service(uuid=bluez.SERIAL_PORT_CLASS)
                # Lookup device names and map to device list
                services = [{**service, 'name': bluez.lookup_name(service['host'])} for service in services]
                # Filter by name
                services = [service for service in services if 'tapio' in service['name'].lower()]

                for service in services:
                    device = {
                        **service,
                        'type': 'BT'
                    }
                    devices.append(SerialDevice(device))

                print(f"Found {len(services)} bluetooth devices")

            except Exception as e:
                print("Error, unable to search Bluetooth devices:", e)

            # Emit the signal with the list of Bluetooth devices
            self.bt_devices_scanned.emit(devices)

    def stop(self):
        # Stop the scanning loop
        self.running = False