"""What the operating system knows about a serial port before anything opens it.

Opening the outgoing Bluetooth port of a paired unit that is switched off
costs the Bluetooth page timeout, 5.12 s, and nothing shortens it. What can
be known for free is which ports are Bluetooth at all, which of those are
outgoing (a paired remote unit behind them) rather than incoming (a listening
port nothing will ever call), which paired unit a port belongs to, and when
Windows last used it. That is the whole of the COM Ports tab in the Bluetooth
settings, and it comes out of the port's hardware id and the paired-device
list in a couple of milliseconds.

The hardware id of a Bluetooth port on Windows looks like

    BTHENUM\\{00001101-...}_LOCALMFG&0002\\7&B265825&0&004B12C02C6A_C00000000

with the remote address before the underscore; an incoming port carries
LOCALMFG&0000 and an all-zero address. The paired-device list comes from the
Bluetooth API in bthprops.cpl. Elsewhere the list is empty, and a Bluetooth
port is treated as outgoing with nothing known about it.
"""

import calendar
import logging
import re
import sys
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

KIND_USB = "usb"
KIND_BLUETOOTH = "bluetooth"
KIND_BLUETOOTH_INCOMING = "bluetooth-incoming"
KIND_OTHER = "other"

_BTHENUM_ADDRESS_RE = re.compile(
    r"BTHENUM\\.*?LOCALMFG&[0-9A-F]+\\[^\\]*&([0-9A-F]{12})_", re.IGNORECASE
)
_NO_REMOTE_ADDRESS = "000000000000"
_NAME_WITH_SERIAL_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<serial>[^()]+)\)\s*$")


@dataclass(frozen=True)
class PortClass:
    """What kind of port this is, and the remote Bluetooth address if any."""
    kind: str
    address: Optional[str] = None

    @property
    def is_bluetooth(self):
        return self.kind in (KIND_BLUETOOTH, KIND_BLUETOOTH_INCOMING)


@dataclass(frozen=True)
class PairedDevice:
    """One entry of the operating system's paired-device list."""
    address: str
    name: str
    last_used: Optional[float]   # epoch seconds, None when never used
    connected: bool


def _text_fields(port_info):
    return (
        getattr(port_info, "device", None),
        getattr(port_info, "description", None),
        getattr(port_info, "name", None),
        getattr(port_info, "product", None),
        getattr(port_info, "manufacturer", None),
        getattr(port_info, "hwid", None),
    )


def matches_bluetooth_marker(port_info, markers):
    """Whether any text the port reports about itself names Bluetooth."""
    folded = tuple(marker.casefold() for marker in markers if marker)
    if not folded:
        return False
    for value in _text_fields(port_info):
        if not value:
            continue
        normalized = str(value).casefold()
        if any(marker in normalized for marker in folded):
            return True
    return False


def classify_port(port_info, bluetooth_markers=()):
    """Sort a port into USB, outgoing Bluetooth, incoming Bluetooth or other.

    The hardware id decides where it can: it carries the remote address of
    an outgoing Bluetooth port and the all-zero address of an incoming one.
    A port that only says "Bluetooth" somewhere in its description, the way
    a Linux rfcomm device does, counts as outgoing with no address known.
    """
    hwid = getattr(port_info, "hwid", None) or ""
    match = _BTHENUM_ADDRESS_RE.search(hwid)
    if match:
        address = match.group(1).upper()
        if address == _NO_REMOTE_ADDRESS:
            return PortClass(KIND_BLUETOOTH_INCOMING)
        return PortClass(KIND_BLUETOOTH, address)
    if matches_bluetooth_marker(port_info, bluetooth_markers):
        return PortClass(KIND_BLUETOOTH)
    if getattr(port_info, "vid", None) is not None:
        return PortClass(KIND_USB)
    return PortClass(KIND_OTHER)


def split_paired_name(name):
    """Split "Tapio RQP Live (1428495563)" into the name and the serial.

    The unit's Bluetooth name carries the same serial number it reports over
    RQP+DEVICEINFO?, so a paired unit can be identified before it is ever
    reached. A name without a parenthesised tail comes back with an empty
    serial.
    """
    if not name:
        return "", ""
    match = _NAME_WITH_SERIAL_RE.match(name)
    if not match:
        return name.strip(), ""
    return match.group("name").strip(), match.group("serial").strip()


def paired_devices():
    """The paired Bluetooth devices, keyed by 12-hex-digit address.

    Empty wherever the Bluetooth API is not available, and on any failure:
    the list is a convenience for naming and ordering, never a condition
    for finding a unit.
    """
    if sys.platform != "win32":
        return {}
    try:
        return _windows_paired_devices()
    except Exception as error:  # pragma: no cover - depends on the host
        log.debug(f"Paired Bluetooth devices unavailable: {error}")
        return {}


# -- Windows Bluetooth API ---------------------------------------------------

_bthprops = None


def _bluetooth_api():
    """The bthprops.cpl functions with their signatures set, loaded once."""
    global _bthprops
    if _bthprops is not None:
        return _bthprops
    import ctypes
    import ctypes.wintypes as wt

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [
            (name, wt.WORD)
            for name in (
                "wYear", "wMonth", "wDayOfWeek", "wDay",
                "wHour", "wMinute", "wSecond", "wMilliseconds",
            )
        ]

    class SEARCH_PARAMS(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("fReturnAuthenticated", wt.BOOL),
            ("fReturnRemembered", wt.BOOL),
            ("fReturnUnknown", wt.BOOL),
            ("fReturnConnected", wt.BOOL),
            ("fIssueInquiry", wt.BOOL),
            ("cTimeoutMultiplier", ctypes.c_ubyte),
            ("hRadio", wt.HANDLE),
        ]

    class DEVICE_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("Address", ctypes.c_ulonglong),
            ("ulClassofDevice", wt.ULONG),
            ("fConnected", wt.BOOL),
            ("fRemembered", wt.BOOL),
            ("fAuthenticated", wt.BOOL),
            ("stLastSeen", SYSTEMTIME),
            ("stLastUsed", SYSTEMTIME),
            ("szName", wt.WCHAR * 248),
        ]

    dll = ctypes.WinDLL("bthprops.cpl")
    dll.BluetoothFindFirstDevice.restype = ctypes.c_void_p
    dll.BluetoothFindFirstDevice.argtypes = [
        ctypes.POINTER(SEARCH_PARAMS), ctypes.POINTER(DEVICE_INFO)
    ]
    dll.BluetoothFindNextDevice.restype = wt.BOOL
    dll.BluetoothFindNextDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(DEVICE_INFO)]
    dll.BluetoothFindDeviceClose.restype = wt.BOOL
    dll.BluetoothFindDeviceClose.argtypes = [ctypes.c_void_p]
    _bthprops = (dll, SEARCH_PARAMS, DEVICE_INFO)
    return _bthprops


def _systemtime_to_epoch(value):
    if value.wYear == 0:
        return None
    # The API reports these in UTC.
    return calendar.timegm((
        value.wYear, value.wMonth, value.wDay,
        value.wHour, value.wMinute, value.wSecond,
    )) + value.wMilliseconds / 1000.0


def _windows_paired_devices():
    import ctypes

    dll, SEARCH_PARAMS, DEVICE_INFO = _bluetooth_api()
    # Remembered devices only, no inquiry: an inquiry occupies the radio for
    # seconds and, as measured, tells nothing about which paired unit is on.
    params = SEARCH_PARAMS(
        ctypes.sizeof(SEARCH_PARAMS), True, True, False, True, False, 0, None
    )
    info = DEVICE_INFO()
    info.dwSize = ctypes.sizeof(DEVICE_INFO)
    found = dll.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
    if not found:
        return {}
    devices = {}
    try:
        while True:
            address = f"{info.Address:012X}"
            devices[address] = PairedDevice(
                address=address,
                name=info.szName,
                last_used=_systemtime_to_epoch(info.stLastUsed),
                connected=bool(info.fConnected),
            )
            info = DEVICE_INFO()
            info.dwSize = ctypes.sizeof(DEVICE_INFO)
            if not dll.BluetoothFindNextDevice(found, ctypes.byref(info)):
                break
    finally:
        dll.BluetoothFindDeviceClose(found)
    return devices
