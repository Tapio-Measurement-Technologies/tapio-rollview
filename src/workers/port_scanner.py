"""
This module contains the worker and related classes for scanning serial ports.
"""

import json
import logging
import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal, QThread
from models.SerialPort import SerialPortItem
from utils.time_sync import send_timestamp
from utils.translation import _
from utils import preferences

log = logging.getLogger(__name__)


class PortScannerWorker(QObject):
    """
    A worker that scans serial ports in a separate thread.

    It iterates through available COM ports, attempts to communicate with
    a device on each port, and emits signals indicating its progress and
    the discovered ports.

    Signals:
        progress(int, str): Emitted to report scanning progress. The first
            argument is the percentage (0-100), and the second is a
            status message.
        finished(list): Emitted when the scan is complete. The argument
            is a list of `SerialPortItem` objects for all discovered ports.
        error(str): Emitted when a significant error occurs that stops
            the scan.
    """
    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._running = True

    def run(self):
        """
        Starts the port scanning process.

        This method should be run in a separate thread. It iterates through
        all available serial ports, checks for a specific device response,
        and builds a list of `SerialPortItem`s.
        """
        self._running = True
        ports = serial.tools.list_ports.comports()
        scanned_ports = []

        if not ports:
            log.info("No COM ports found.")
            self.progress.emit(100, _("PORTSCAN_NO_PORTS_FOUND_TEXT"))
            self.finished.emit([])
            return

        for index, port_info in enumerate(ports):
            if not self._running:
                break

            progress_percent = int(((index + 1) / len(ports)) * 100)
            self.progress.emit(
                progress_percent,
                f"{_('PORTSCAN_SCANNING_PORT_TEXT')} '{port_info.device}'...",
            )
            log.debug(f"Scanning port: {port_info.device}")

            device_responded = False
            port = None
            try:
                if not self._running:
                    break

                port = serial.Serial(
                    port=port_info.device,
                    baudrate=115200,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.2,
                    write_timeout=0.2,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )

                if not self._running:
                    break

                port.write(b"RQP+DEVICEINFO?\n")
                response = port.readline().decode("utf-8").strip()

                if self._running and response:
                    log.debug(f"Port {port_info.device} response: {response}")
                    try:
                        response_data = json.loads(response)
                        if (
                            "deviceName" in response_data
                            and "serialNumber" in response_data
                        ):
                            port_info.description = response_data["deviceName"]
                            port_info.serial_number = response_data["serialNumber"]
                            device_responded = True
                            send_timestamp(port)
                    except json.JSONDecodeError:
                        log.warning(
                            f"Could not decode JSON from port {port_info.device}: {response}"
                        )

            except (serial.SerialException, OSError) as e:
                log.debug(f"Error opening or reading from port {port_info.device}: {e}")
            finally:
                if port and port.is_open:
                    port.close()

            if not self._running:
                break

            scanned_ports.append(SerialPortItem(port_info, device_responded))

        log.info(f"Port scan finished. Found {len(scanned_ports)} ports.")
        self.finished.emit(scanned_ports)

    def stop(self):
        """
        Stops the scanning process.
        """
        self._running = False
        log.info("Stopping port scanner.")


class PortScanner(QObject):
    """
    Manages the port scanning process in a separate thread.
    """

    progress = Signal(int, str)
    finished = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    def start(self):
        """
        Starts the port scan.
        """
        self._thread = QThread()
        self._worker = PortScannerWorker()

        self._worker.moveToThread(self._thread)

        # Connect signals
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self.finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.started.connect(self._worker.run)

        log.info("Starting port scanner thread.")
        self._thread.start()

    def stop(self):
        """
        Stops the port scan if it's running.
        """
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            log.info("Stopping port scanner thread.")
            self._thread.quit()

    def is_running(self):
        return self._thread and self._thread.isRunning()