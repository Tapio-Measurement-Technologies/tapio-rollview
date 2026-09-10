"""A serial transport that leaves the port alone once it is open.

rqft's own SerialTransport sets pyserial's timeout on every read, and
pyserial answers a timeout change by writing the whole port configuration
back to the driver: on Windows that is SetCommState, on POSIX tcsetattr.
The USB CDC driver passes a configuration write on to the device as a fresh
control-line state, and the Teensy core takes a control-line change as the
port having only just been opened: Serial reads as connected only once DTR
has stood for 15 ms. A session pumped every few tens of milliseconds kept
that clock restarting, so the unit's 1.2.0 firmware, which takes its USB
link from that flag, saw the cable flapping through a working session. The
worst of what it did with that was to tell the operator RollView had not
answered a sync it was in the middle of answering.

So the port is configured once, at open, and never touched again. A read
blocks for one short slice; a longer wait is a loop of them, and a wait of
zero takes only what has already arrived.
"""
import time

import serial

# One blocking read. Short enough that a caller asking for less is not kept
# waiting noticeably, long enough that a quiet link is not a busy loop.
READ_SLICE_S = 0.005


class SteadySerialTransport:
    """rqft.client.ByteTransport over pyserial, configured once."""

    def __init__(self, port, *, baudrate=115200, **kwargs):
        kwargs.setdefault("timeout", READ_SLICE_S)
        self._serial = serial.Serial(port=port, baudrate=baudrate, **kwargs)

    def write(self, data):
        written = self._serial.write(data)
        if written is not None and written != len(data):
            raise OSError("serial write accepted fewer bytes than requested")

    def read(self, max_len, timeout):
        """Up to max_len bytes, waiting at most ``timeout`` seconds for the
        first of them. Empty when nothing arrived in time."""
        if max_len <= 0:
            raise ValueError("max_len must be positive")
        if timeout <= 0:
            waiting = self._serial.in_waiting
            if waiting <= 0:
                return b""
            return bytes(self._serial.read(min(waiting, max_len)))
        deadline = time.monotonic() + timeout
        while True:
            data = bytes(self._serial.read(max_len))
            if data or time.monotonic() >= deadline:
                return data

    def close(self):
        self._serial.close()
