import time
import serial.tools.list_ports
from modem import ZMODEM
from modem.const import CAN_SEQ
from models.FileTransfer import FileTransferModel, FileTransferItem
from PySide6.QtCore import QThread, Signal

class FileTransferThread(QThread):
    receivingFile = Signal(str, int) # (filename, filesLeft)

    def __init__(self, folder_path, serial):
        super().__init__()
        self.folder_path = folder_path
        self.serial = serial

    def run(self):
        def getc(size, timeout=5):
            data = self.serial.read(size).decode("ISO-8859-1")
            print(data)
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

def list_com_ports():
    ports = serial.tools.list_ports.comports()
    return ports
