"""
This module contains the worker and related classes for scanning serial ports.
"""

import json
import logging
import serial
import serial.tools.list_ports
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QObject, Signal, QThread
import settings
from models.SerialPort import SerialPortItem, natural_sort_key
from serial.tools import list_ports_common
from utils.time_sync import send_timestamp
from utils.translation import _
from utils import preferences
import os

log = logging.getLogger(__name__)


class PortScannerWorker(QObject):
    """
    A worker that scans serial ports in a separate thread using a thread pool.

    It uses a thread pool to scan all available COM ports simultaneously,
    attempts to communicate with a device on each port, and emits signals
    indicating its progress and the discovered ports.

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

    def __init__(self, max_workers=None):
        super().__init__()
        self._running = True
        self._max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)

    def _allowed_usb_ids(self):
        return {
            (self._coerce_id(vid), self._coerce_id(pid))
            for vid, pid in getattr(settings, "ALLOWED_SERIAL_USB_IDS", set())
        }

    def _coerce_id(self, value):
        if isinstance(value, str):
            return int(value, 0)
        return int(value)

    def _bluetooth_serial_markers(self):
        return tuple(
            marker.casefold()
            for marker in getattr(settings, "SERIAL_BLUETOOTH_PORT_MARKERS", ())
            if marker
        )

    def _port_text_fields(self, port_info):
        return (
            getattr(port_info, "device", None),
            getattr(port_info, "description", None),
            getattr(port_info, "name", None),
            getattr(port_info, "product", None),
            getattr(port_info, "manufacturer", None),
            getattr(port_info, "hwid", None),
        )

    def _matches_allowed_usb_id(self, port_info):
        vid = getattr(port_info, "vid", None)
        pid = getattr(port_info, "pid", None)
        if vid is None or pid is None:
            return False
        return (int(vid), int(pid)) in self._allowed_usb_ids()

    def _matches_bluetooth_serial_port(self, port_info):
        markers = self._bluetooth_serial_markers()
        if not markers:
            return False

        for value in self._port_text_fields(port_info):
            if not value:
                continue
            normalized = str(value).casefold()
            if any(marker in normalized for marker in markers):
                return True
        return False

    def _should_probe_port(self, port_info):
        if port_info.device in preferences.pinned_serial_ports:
            return True
        return (
            self._matches_allowed_usb_id(port_info)
            or self._matches_bluetooth_serial_port(port_info)
        )

    def _scan_single_port(self, port_info):
        """
        Scans a single port for device communication.

        Args:
            port_info: The port information object from serial.tools.list_ports

        Returns:
            tuple: (port_info, device_responded, error_message)
        """
        if not self._running:
            return port_info, False, "Scan cancelled"

        device_responded = False
        port = None
        error_message = None

        try:
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
                return port_info, False, "Scan cancelled"

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
            error_message = str(e)
            log.debug(f"Error opening or reading from port {port_info.device}: {e}")
        finally:
            if port and port.is_open:
                port.close()

        return port_info, device_responded, error_message

    def run(self):
        """
        Starts the port scanning process using a thread pool.

        This method should be run in a separate thread. It uses a thread pool
        to scan all available serial ports simultaneously, checks for a specific
        device response, and builds a list of `SerialPortItem`s.
        """
        self._running = True
        ports = list(serial.tools.list_ports.comports())
        scanned_ports = []
        discovered_devices = {port.device for port in ports}

        for device in sorted(preferences.pinned_serial_ports, key=natural_sort_key):
            if device in discovered_devices:
                continue
            port_info = list_ports_common.ListPortInfo(device)
            port_info.description = ""
            port_info.serial_number = ""
            ports.append(port_info)

        if not ports:
            log.info("No COM ports found.")
            self.progress.emit(100, _("PORTSCAN_NO_PORTS_FOUND_TEXT"))
            self.finished.emit([])
            return

        ports_to_probe = [port for port in ports if self._should_probe_port(port)]
        skipped_ports = [port for port in ports if port not in ports_to_probe]

        scanned_ports.extend(SerialPortItem(port_info, False) for port_info in skipped_ports)

        if not ports_to_probe:
            log.info("No matching COM ports found.")
            self.progress.emit(100, _("PORTSCAN_COMPLETE_TEXT"))
            self.finished.emit(scanned_ports)
            return

        log.info(f"Starting parallel scan of {len(ports_to_probe)} candidate ports using {self._max_workers} workers")

        # Use ThreadPoolExecutor to scan ports in parallel
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # Submit all port scanning tasks
            future_to_port = {
                executor.submit(self._scan_single_port, port_info): port_info
                for port_info in ports_to_probe
            }

            completed_count = 0
            total_ports = len(ports_to_probe)

            # Process completed tasks as they finish
            for future in as_completed(future_to_port):
                if not self._running:
                    # Cancel remaining tasks
                    for f in future_to_port:
                        f.cancel()
                    break

                try:
                    port_info, device_responded, error_message = future.result()
                    completed_count += 1

                    # Update progress
                    progress_percent = int((completed_count / total_ports) * 100)
                    status_msg = f"{_('PORTSCAN_SCANNING_PORT_TEXT')} '{port_info.device}'... ({completed_count}/{total_ports})"
                    self.progress.emit(progress_percent, status_msg)

                    # Add result to scanned ports
                    scanned_ports.append(SerialPortItem(port_info, device_responded))

                    if error_message and error_message != "Scan cancelled":
                        log.debug(f"Port {port_info.device} scan error: {error_message}")

                except Exception as e:
                    completed_count += 1
                    log.error(f"Unexpected error scanning port: {e}")
                    # Add the port with error status
                    port_info = future_to_port[future]
                    scanned_ports.append(SerialPortItem(port_info, False))

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

    def __init__(self, parent=None, max_workers=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._max_workers = max_workers

    def start(self):
        """
        Starts the port scan.
        """
        self._thread = QThread()
        self._worker = PortScannerWorker(max_workers=self._max_workers)

        self._worker.moveToThread(self._thread)

        # Connect signals
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self.finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
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
        if self.is_running():
            log.info("Stopping port scanner thread.")
            self._thread.quit()

    def is_running(self):
        if not self._thread:
            return False

        try:
            return self._thread.isRunning()
        except RuntimeError:
            self._clear_thread_refs()
            return False

    def _on_thread_finished(self):
        self._clear_thread_refs()

    def _clear_thread_refs(self):
        self._thread = None
        self._worker = None
