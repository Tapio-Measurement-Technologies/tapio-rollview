import time
import serial.tools.list_ports
from modem import ZMODEM
from modem.const import CAN_SEQ
from models.FileTransfer import FileTransferModel, FileTransferItem
from models.SerialPort import SerialPortItem
from PySide6.QtCore import QThread, Signal
from utils.time_sync import send_timestamp
import json

class FileTransferThread(QThread):
    receivingFile = Signal(str, int) # (filename, filesLeft)

    def __init__(self, folder_path, serial):
        super().__init__()
        self.folder_path = folder_path
        self.serial = serial

    def run(self):
        def getc(size, timeout=5):
            data = self.serial.read(size).decode("ISO-8859-1")
            return data

        def putc(data: str, timeout=8):
            pbytes = self.serial.write(data.encode("ISO-8859-1"))
            self.serial.flush()
            return pbytes or None

        self.serial.readall()
        time.sleep(0.1)

        zmodem = ZMODEM(getc, putc, self)
        zmodem.recv(self.folder_path)
        self.serial.close()

    def stop(self):
        if self.serial.is_open:
            self.serial.write(CAN_SEQ)
            self.serial.close()

class FileTransferManager:
    def __init__(self):
        self.serial: serial.Serial = None
        self.thread: FileTransferThread = None
        self.model: FileTransferModel = FileTransferModel()

    def start_transfer(self, port, folder_path, on_complete):
        try:
            self.model.removeItems()
            self.serial = serial.Serial(port=port,parity=serial.PARITY_NONE,bytesize=serial.EIGHTBITS,stopbits=serial.STOPBITS_ONE,timeout=0.2,xonxoff=0,rtscts=0,dsrdtr=0,baudrate=115200)
            self.thread = FileTransferThread(folder_path, self.serial)
            self.thread.receivingFile.connect(self.update_progress)
            self.thread.finished.connect(on_complete)
            self.thread.start()
        except:
            self.cancel_transfer()

    def cancel_transfer(self):
        self.model.removeItems()
        if self.thread is not None:
            self.thread.stop()

    def update_progress(self, filename, filesLeft):
        self.model.addItem(FileTransferItem(filename, filesLeft))

def scan_ports(show_all_ports = False):
    ports = serial.tools.list_ports.comports()
    valid_ports = []

    if show_all_ports:
        valid_ports = [ SerialPortItem(port) for port in ports ]
        return valid_ports

    for port_info in ports:
        try:
            port = serial.Serial(port_info.device, timeout=1)  # Open the serial port
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

    return valid_ports
