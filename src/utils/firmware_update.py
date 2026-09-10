"""Writing a firmware image to the device over USB.

The device's own bootloader takes the image. It is reached by asking the
running firmware to restart into it: setting the USB serial line to 134
baud is the signal, and about a tenth of a second later the device is
back on the bus as a HID device instead of a serial port. That device
takes the image in 1 KB blocks, each in one output report: a 64-byte
header carrying the flash address, then the block. The first block erases
the flash and takes a while; every block may be refused while the device
is still busy with the last, which shows as a failed write, so a write is
simply tried again. A block addressed past the end of flash is the reboot
command, and the device comes back as a serial port with the new firmware
running.

Nothing here knows about Qt. FirmwareUpdater reports through callbacks and
raises FirmwareUpdateError, with a ``kind`` the GUI turns into words. The
HID access is the operating system's own: the HID class driver on Windows,
hidraw on Linux. No extra library, nothing to install.
"""
import logging
import os
import sys
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from utils.firmware_image import FLASH_BASE

log = logging.getLogger(__name__)

#: The device's USB identity: as a serial port when running, and as the
#: HID device its bootloader presents.
USB_VID = 0x16C0
RUNNING_PID = 0x0483
BOOTLOADER_PID = 0x0478
#: The bootloader's HID usage names the board it is on; this is the one in
#: the device. Checked where the platform can read it, so a look-alike
#: board plugged into the same computer is never written.
BOOTLOADER_USAGE_PAGE = 0xFF9C
BOOTLOADER_USAGE = 0x25

#: The baud rate that asks the running firmware to restart into the bootloader.
REBOOT_BAUDRATE = 134

BLOCK_SIZE = 1024
_HEADER_SIZE = 64
#: One output report: report id, header, block.
REPORT_SIZE = 1 + _HEADER_SIZE + BLOCK_SIZE
#: The address that means "reboot" rather than "write".
_REBOOT_ADDRESS = 0xFFFFFF

#: How long the bootloader gets to appear after the restart signal, how
#: long the new firmware gets to enumerate after the reboot command, and
#: how long one block write may block. The first block erases the whole
#: flash, which is the slow one.
BOOTLOADER_APPEAR_TIMEOUT_S = 12.0
DEVICE_RETURN_TIMEOUT_S = 16.0
WRITE_TIMEOUT_MS = 10000
#: A write the bootloader refuses is retried this many times, this far apart.
WRITE_TRIES = 250
WRITE_RETRY_DELAY_S = 0.1
#: A pause after the first block (the erase) and after every other one.
FIRST_BLOCK_PAUSE_S = 0.5
BLOCK_PAUSE_S = 0.01
#: How long the running device's port is tried for before it is called
#: busy: the connection that held it has only just been told to let go.
PORT_OPEN_TIMEOUT_S = 3.0
#: The reboot command is retried less patiently: the device is gone once
#: it has taken it, and a refusal then is the success.
REBOOT_TRIES = 25
REBOOT_RETRY_DELAY_S = 0.02


class FirmwareUpdateError(Exception):
    """The update did not complete. ``kind`` says at which step:
    port | no_bootloader | write | not_back."""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind


# -- the wire format ---------------------------------------------------------

def block_report(address, data):
    """The output report that writes ``data`` at ``address``.

    The header carries the low 24 bits of the address; the flash base is
    above them, so the bootloader is told an offset into the flash. The
    block is zero-padded to its full size, since a report is a fixed
    length and the bootloader writes the whole of it.
    """
    if len(data) > BLOCK_SIZE:
        raise ValueError("block too large")
    report = bytearray(REPORT_SIZE)
    report[1] = address & 0xFF
    report[2] = (address >> 8) & 0xFF
    report[3] = (address >> 16) & 0xFF
    report[1 + _HEADER_SIZE:1 + _HEADER_SIZE + len(data)] = data
    return bytes(report)


def reboot_report():
    return block_report(_REBOOT_ADDRESS, b"")


def plan_blocks(image):
    """The (address, bytes) blocks an image is written as, in order.

    Blocks the file has nothing for are left out: the erase at the first
    block already set them to blank, and the bootloader has no need to be
    told so. The first block is always written, since it is the erase.
    """
    blocks = []
    address = FLASH_BASE
    while address < image.max_address:
        data, filled = image.read(address, BLOCK_SIZE)
        if filled or address == FLASH_BASE:
            blocks.append((address, data.rstrip(b"\x00") if filled else b""))
        address += BLOCK_SIZE
    return blocks


# -- finding and driving the device -------------------------------------------

@dataclass
class BootloaderDevice:
    """One bootloader on the bus, as a path the platform can open."""
    path: str


def _list_hid_paths():
    """Every HID device path on the system, with (vid, pid)."""
    if sys.platform == "win32":
        from utils import win32_hid
        return win32_hid.enumerate()
    if sys.platform.startswith("linux"):
        return _linux_enumerate()
    return []


def _linux_usage(path):
    """(usage page, usage) from a hidraw device's report descriptor, or
    None when it cannot be read.

    The bootloader's usage names the board it is on, and it is the only
    thing that tells one Teensy's bootloader from another's: they share a
    USB product id. Windows hands the pair over through the HID class
    driver; on Linux the report descriptor is where it is written down.
    """
    name = os.path.basename(path)
    try:
        with open(f"/sys/class/hidraw/{name}/device/report_descriptor", "rb") as handle:
            descriptor = handle.read()
    except OSError:
        return None
    page = usage = None
    index = 0
    while index < len(descriptor) and (page is None or usage is None):
        prefix = descriptor[index]
        index += 1
        size = prefix & 0x03
        size = 4 if size == 3 else size
        value = int.from_bytes(descriptor[index:index + size], "little") if size else 0
        index += size
        tag = prefix & 0xFC
        if tag == 0x04 and page is None:      # Usage Page (global)
            page = value
        elif tag == 0x08 and usage is None:   # Usage (local)
            usage = value
    if page is None or usage is None:
        return None
    return page, usage


def _linux_enumerate():
    found = []
    base = "/sys/class/hidraw"
    try:
        names = os.listdir(base)
    except OSError:
        return found
    for name in names:
        try:
            with open(os.path.join(base, name, "device", "uevent"), "r") as handle:
                uevent = handle.read()
        except OSError:
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                parts = line[len("HID_ID="):].split(":")
                if len(parts) == 3:
                    found.append((f"/dev/{name}", int(parts[1], 16), int(parts[2], 16)))
    return found


def find_bootloader(exclude=()):
    """The device's bootloader if it is on the bus, else None.

    ``exclude`` names paths that were already there. A restart is answered
    by a bootloader that was not on the bus before it, so another board
    sitting in update mode on the same machine is never taken for the one
    that was asked to restart.
    """
    for path, vid, pid in _list_hid_paths():
        if vid == USB_VID and pid == BOOTLOADER_PID and path not in exclude:
            return BootloaderDevice(path)
    return None


def bootloader_paths():
    """Every bootloader on the bus now, as a set of paths."""
    return {path for path, vid, pid in _list_hid_paths()
            if vid == USB_VID and pid == BOOTLOADER_PID}


def open_bootloader(device):
    """A handle with ``write(report)`` and ``close()``."""
    if sys.platform == "win32":
        from utils import win32_hid
        return win32_hid.open_output(
            device.path, REPORT_SIZE, WRITE_TIMEOUT_MS,
            usage_page=BOOTLOADER_USAGE_PAGE, usage=BOOTLOADER_USAGE,
        )
    identity = _linux_usage(device.path)
    if identity is None:
        raise OSError(
            f"could not read what board {device.path} is; refusing to write to it"
        )
    if identity != (BOOTLOADER_USAGE_PAGE, BOOTLOADER_USAGE):
        raise OSError(
            f"not this device's bootloader (usage {identity[0]:#x}/{identity[1]:#x})"
        )
    return _LinuxHidraw(device.path)


class _LinuxHidraw:
    def __init__(self, path):
        self._fd = os.open(path, os.O_RDWR)

    def write(self, report):
        written = os.write(self._fd, report)
        if written != len(report):
            raise OSError("short write")

    def close(self):
        os.close(self._fd)


def find_running_port(serial_number=None):
    """The serial port a running device is on, or None.

    With a serial number, only that unit answers. Several units share one
    computer, and "some RQP Live is on the bus" says nothing about the one
    that was just written.
    """
    for port in list_ports.comports():
        if port.vid != USB_VID or port.pid != RUNNING_PID:
            continue
        if serial_number and (port.serial_number or "") != serial_number:
            continue
        return port.device
    return None


def port_serial_number(port_name):
    """The USB serial number of the unit on ``port_name``, or None when the
    port is gone or reports none."""
    for port in list_ports.comports():
        if port.device == port_name:
            return port.serial_number or None
    return None


def request_bootloader(port_name):
    """Ask the firmware on ``port_name`` to restart into its bootloader.

    Opening the port at the magic baud rate is the whole signal. The port
    is closed again at a normal rate, so a system that remembers line
    settings does not send the device straight back into the bootloader
    the next time anything opens it.
    """
    # The connection that held the port has only just been asked to let
    # go, so the open is tried for a while before the port is called busy.
    deadline = time.monotonic() + PORT_OPEN_TIMEOUT_S
    while True:
        try:
            handle = serial.Serial(port_name, REBOOT_BAUDRATE, timeout=0.1, write_timeout=0.5)
            break
        except (serial.SerialException, OSError) as e:
            if time.monotonic() >= deadline:
                raise FirmwareUpdateError("port", str(e)) from e
            time.sleep(0.1)
    try:
        time.sleep(0.1)
        try:
            handle.baudrate = 115200
        except (serial.SerialException, OSError):
            # Already gone: the restart was that quick.
            pass
    finally:
        try:
            handle.close()
        except (serial.SerialException, OSError):
            pass


class FirmwareUpdater:
    """Run one update: restart, wait, write, reboot, wait for the return.

    ``status(step)`` is told which of those is under way, with step one of
    restarting | waiting | uploading | rebooting | returning.
    ``progress(done, total)`` counts bytes written. Every wait is bounded,
    and every failure is a FirmwareUpdateError naming its step.

    The seams (``find_bootloader``, ``open_bootloader`` and the rest) are
    attributes so a test can stand a fake device behind them.
    """

    def __init__(self, status=None, progress=None, sleep=time.sleep, clock=time.monotonic):
        self._status = status or (lambda step: None)
        self._progress = progress or (lambda done, total: None)
        self._sleep = sleep
        self._clock = clock
        self.find_bootloader = find_bootloader
        self.bootloader_paths = bootloader_paths
        self.open_bootloader = open_bootloader
        self.request_bootloader = request_bootloader
        self.find_running_port = find_running_port
        self.port_serial_number = port_serial_number
        self.cancelled = lambda: False

    def run(self, image, port_name=None):
        """Write ``image`` to the unit on ``port_name``, or to the one
        already in update mode when ``port_name`` is None.

        With a port name the unit on it is the one written, whatever else
        is on the bus: it is restarted, and the bootloader that answers is
        one that was not there before. Without one this is the recovery
        path, and the bootloader already on the bus is the subject.
        """
        serial_number = None
        if port_name is not None:
            # Read before the restart: the port is about to go away.
            serial_number = self.port_serial_number(port_name)
            already = self.bootloader_paths()
            self._status("restarting")
            self.request_bootloader(port_name)
            self._status("waiting")
            device = self._wait_for(
                lambda: self.find_bootloader(already), BOOTLOADER_APPEAR_TIMEOUT_S
            )
            if device is None:
                raise FirmwareUpdateError("no_bootloader", "the bootloader did not appear")
        else:
            device = self.find_bootloader()
            if device is None:
                raise FirmwareUpdateError("no_bootloader", "no device in update mode")
        handle = self.open_bootloader(device)
        try:
            self._write_image(handle, image)
            self._status("rebooting")
            self._send(handle, reboot_report(), REBOOT_TRIES, REBOOT_RETRY_DELAY_S, tolerate=True)
        finally:
            try:
                handle.close()
            except Exception:
                pass
        # The unit that was written has to leave update mode and be seen
        # running again. The reboot report is allowed to go unanswered
        # above because a device that has taken it is gone from the bus;
        # this is what tells that apart from one that stalled and is still
        # sitting in the bootloader on a flash that was erased at block 0.
        # Only this unit's own path counts: another board in update mode
        # elsewhere on the bench has nothing to do with this update.
        written = device.path
        self._status("returning")
        port = self._wait_for(
            lambda: None if written in self.bootloader_paths()
            else self.find_running_port(serial_number),
            DEVICE_RETURN_TIMEOUT_S,
        )
        if port is None:
            raise FirmwareUpdateError("not_back", "the device did not come back")
        return port

    def _write_image(self, handle, image):
        blocks = plan_blocks(image)
        total = sum(max(len(data), 1) for _address, data in blocks)
        done = 0
        self._status("uploading")
        self._progress(0, total)
        for index, (address, data) in enumerate(blocks):
            if self.cancelled():
                raise FirmwareUpdateError("write", "cancelled")
            self._send(handle, block_report(address, data), WRITE_TRIES, WRITE_RETRY_DELAY_S)
            self._sleep(FIRST_BLOCK_PAUSE_S if index == 0 else BLOCK_PAUSE_S)
            done += max(len(data), 1)
            self._progress(done, total)

    def _send(self, handle, report, tries, delay, tolerate=False):
        """Write one report, again after a refusal, up to ``tries`` times.

        The bootloader refuses a report while it is still busy with the
        last one, and the refusal reaches here as an OSError. With
        ``tolerate`` a refusal that never clears is not a failure: the
        reboot command takes the device off the bus, so the write after
        the one that worked cannot succeed.
        """
        last = None
        for attempt in range(tries):
            try:
                handle.write(report)
                return
            except OSError as e:
                last = e
                if attempt + 1 < tries:
                    self._sleep(delay)
        if tolerate:
            log.debug(f"Reboot report not taken: {last}")
            return
        raise FirmwareUpdateError("write", str(last)) from last

    def _wait_for(self, probe, timeout_s):
        deadline = self._clock() + timeout_s
        while True:
            found = probe()
            if found is not None:
                return found
            if self._clock() >= deadline:
                return None
            self._sleep(0.1)
