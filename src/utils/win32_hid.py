"""HID output on Windows, through the class driver Windows ships.

Enough of SetupAPI and hid.dll to find a HID device by its USB identity,
check which board its bootloader claims to be, and write output reports
to it with a deadline. Only what the firmware update needs; nothing here
reads input.
"""
import ctypes
from ctypes import wintypes

_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_hid = ctypes.WinDLL("hid", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_DIGCF_PRESENT = 0x02
_DIGCF_DEVICEINTERFACE = 0x10
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_FILE_FLAG_OVERLAPPED = 0x40000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_HIDP_STATUS_SUCCESS = 0x00110000


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.POINTER(ctypes.c_ulong)),
        ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
    ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HIDD_ATTRIBUTES)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.restype = ctypes.c_long
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS)]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(_OVERLAPPED),
]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.CancelIoEx.restype = wintypes.BOOL
_kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _interface_paths():
    """Every HID interface path present on the system."""
    guid = _GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info_set = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE
    )
    if info_set == _INVALID_HANDLE_VALUE:
        return []
    paths = []
    try:
        index = 0
        while True:
            data = _SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                info_set, None, ctypes.byref(guid), index, ctypes.byref(data)
            ):
                break
            index += 1
            needed = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info_set, ctypes.byref(data), None, 0, ctypes.byref(needed), None
            )
            if not needed.value:
                continue
            detail = ctypes.create_string_buffer(needed.value)
            # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: DWORD + one WCHAR,
            # padded to pointer size on 64-bit.
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            )
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info_set, ctypes.byref(data), detail, needed, None, None
            ):
                paths.append(ctypes.wstring_at(ctypes.addressof(detail) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info_set)
    return paths


def _open_handle(path, access):
    handle = _kernel32.CreateFileW(
        path, access, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None,
        _OPEN_EXISTING, _FILE_FLAG_OVERLAPPED, None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), f"could not open {path}")
    return handle


def _attributes(handle):
    attributes = _HIDD_ATTRIBUTES()
    attributes.Size = ctypes.sizeof(attributes)
    if not _hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
        return None
    return attributes


def _caps(handle):
    preparsed = ctypes.c_void_p()
    if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        return None
    try:
        caps = _HIDP_CAPS()
        if _hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != _HIDP_STATUS_SUCCESS:
            return None
        return caps
    finally:
        _hid.HidD_FreePreparsedData(preparsed)


def enumerate():
    """(path, vid, pid) for every HID device that will say who it is."""
    found = []
    for path in _interface_paths():
        # Opened without read or write access: enough to ask the identity,
        # and it does not need the device to be free.
        try:
            handle = _open_handle(path, 0)
        except OSError:
            continue
        try:
            attributes = _attributes(handle)
        finally:
            _kernel32.CloseHandle(handle)
        if attributes is not None:
            found.append((path, attributes.VendorID, attributes.ProductID))
    return found


class OutputDevice:
    """A HID device open for output reports, each written with a deadline."""

    def __init__(self, path, report_size, timeout_ms, usage_page=None, usage=None):
        self._handle = _open_handle(path, _GENERIC_READ | _GENERIC_WRITE)
        self._timeout_ms = timeout_ms
        self._report_size = report_size
        caps = _caps(self._handle)
        if caps is not None:
            if usage_page is not None and (caps.UsagePage, caps.Usage) != (usage_page, usage):
                _kernel32.CloseHandle(self._handle)
                raise OSError(
                    f"not the device's bootloader (usage {caps.UsagePage:#x}/{caps.Usage:#x})"
                )
            if caps.OutputReportByteLength:
                # The driver wants every output report at exactly the length
                # the descriptor declares.
                self._report_size = caps.OutputReportByteLength
        self._event = _kernel32.CreateEventW(None, True, False, None)

    def write(self, report):
        if len(report) < self._report_size:
            report = bytes(report) + bytes(self._report_size - len(report))
        buffer = ctypes.create_string_buffer(bytes(report), len(report))
        overlapped = _OVERLAPPED()
        overlapped.hEvent = self._event
        written = wintypes.DWORD()
        ok = _kernel32.WriteFile(
            self._handle, buffer, len(report), ctypes.byref(written), ctypes.byref(overlapped)
        )
        if not ok:
            error = ctypes.get_last_error()
            if error != _ERROR_IO_PENDING:
                raise OSError(error, "write refused")
            waited = _kernel32.WaitForSingleObject(self._event, self._timeout_ms)
            if waited != _WAIT_OBJECT_0:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                _kernel32.GetOverlappedResult(
                    self._handle, ctypes.byref(overlapped), ctypes.byref(written), True
                )
                raise OSError("write timed out")
            if not _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(overlapped), ctypes.byref(written), False
            ):
                raise OSError(ctypes.get_last_error(), "write failed")
        if written.value != len(report):
            raise OSError("short write")

    def close(self):
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._event is not None:
            _kernel32.CloseHandle(self._event)
            self._event = None


def open_output(path, report_size, timeout_ms, usage_page=None, usage=None):
    return OutputDevice(path, report_size, timeout_ms, usage_page=usage_page, usage=usage)
