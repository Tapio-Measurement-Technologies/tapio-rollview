"""A fake RQFT device on a pseudo-terminal, for testing the real sync path.

The app's device workflow — scan a port, read device info, then pull profiles
over ZMODEM — could previously only be tested by mocking ``serial.Serial``, which
skips the protocol entirely. This module puts a real file descriptor on the other
end instead: ``pty.openpty()`` gives a ``/dev/pts/N`` the app opens with pyserial
exactly as it would open a physical device.

    with FakeRqftDevice(profiles={"250520-134139/a.prof": b"..."}) as device, \\
         device.patch_comports():
        ...  # the app can now scan, find the device, and sync from it

``src/modem`` implements ZMODEM *receive* only, so the sender here is written
against that receiver: binary headers with 16-bit CRCs throughout, one ZDATA
frame per file. It reuses the app's own ``crc16``, so the two cannot disagree.

POSIX only — ``pty`` has no Windows equivalent. The test modules that use this
guard their import with ``pytest.importorskip("pty")`` so a Windows run skips
them instead of failing to collect.
"""

import json
import os
import pty
import struct
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

from serial.tools import list_ports_common

from modem.tools import crc16

# Mirrored from modem/const.py — imported by value so a change there shows up as
# a test failure rather than a silently divergent fake.
ZPAD = 0x2A
ZDLE = 0x18
ZBIN = 0x41
ZHEX = 0x42
ZRQINIT = 0x00
ZRINIT = 0x01
ZACK = 0x03
ZFILE = 0x04
ZNAK = 0x06
ZFIN = 0x08
ZRPOS = 0x09
ZDATA = 0x0A
ZEOF = 0x0B
ZCRCE = 0x68
ZCRCG = 0x69
ZCRCW = 0x6B
XON = 0x11

# Bytes that must never appear raw in the stream.
_ESCAPED = {ZDLE, 0x10, 0x90, 0x11, 0x91, 0x13, 0x93}

DEFAULT_VID = 0x16C0
DEFAULT_PID = 0x0483

SUBPACKET_SIZE = 1024

# models/Profile.py: PROF_FILE_HEADER_SIZE
PROF_FILE_HEADER_SIZE = 128


def _escape(data):
    out = bytearray()
    for byte in data:
        if byte in _ESCAPED:
            out.append(ZDLE)
            out.append(byte ^ 0x40)
        else:
            out.append(byte)
    return bytes(out)


def _crc16_bytes(data, crc=0):
    """The app's crc16 over a bytes object (it takes latin-1 text)."""
    return crc16(data.decode("ISO-8859-1"), crc)


def make_profile_bytes(
    hardnesses=None,
    sample_step=0.02,
    serial_number="FAKE-0001",
    prof_version=1,
):
    """Build a valid .prof payload the app's parser accepts.

    Layout (see models/Profile.py): a 128-byte header of
    ``prof_version`` (uint32 LE), ``serial_number`` (32 bytes, NUL-padded) and
    ``sample_step`` (float32), then one float32 hardness sample per point.

    Without arguments it produces a plausible-looking roll profile, which is what
    you want when the point is to see the plot render.
    """
    if hardnesses is None:
        import math

        hardnesses = [
            40.0 + 6.0 * math.sin(i / 40.0) + 2.0 * math.sin(i / 7.0)
            for i in range(600)
        ]

    header = bytearray(PROF_FILE_HEADER_SIZE)
    header[0:4] = int(prof_version).to_bytes(4, "little", signed=False)
    encoded = serial_number.encode("ISO-8859-1")[:31]
    header[4 : 4 + len(encoded)] = encoded
    header[36:40] = struct.pack("f", float(sample_step))

    body = b"".join(struct.pack("f", float(value)) for value in hardnesses)
    return bytes(header) + body


class FakeRqftDevice:
    """A pseudo-terminal that answers RQP commands and sends files over ZMODEM.

    Args:
        profiles: ``{relative/path.prof: bytes}`` to offer during a sync.
        device_name: reported as ``deviceName`` in the DEVICEINFO response.
        serial_number: reported as ``serialNumber``.
        respond_to_deviceinfo: set False to simulate a silent/unresponsive port.
    """

    def __init__(
        self,
        profiles=None,
        device_name="RQP Fake",
        serial_number="FAKE-0001",
        respond_to_deviceinfo=True,
    ):
        self.profiles = dict(profiles or {})
        self.device_name = device_name
        self.serial_number = serial_number
        self.respond_to_deviceinfo = respond_to_deviceinfo

        self.port = None
        self._master = None
        self._slave = None
        self._thread = None
        self._stop = threading.Event()
        # Headers arrive in arbitrary read chunks, so the parse buffer has to
        # outlive a single _await_header call: a ZACK and the ZRPOS that follows
        # it routinely land in the same read.
        self._rxbuf = bytearray()

        # Observable history, for asserting on what the app actually sent.
        self.commands = []
        self.timestamps = []
        self.files_sent = []
        self.errors = []

    # ------------------------------------------------------------- lifecycle

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info):
        self.stop()

    def start(self):
        self._master, self._slave = pty.openpty()
        self.port = os.ttyname(self._slave)
        os.set_blocking(self._master, False)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout=5):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        for fd in (self._master, self._slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._master = self._slave = None

    def wait_for(self, predicate, timeout=5.0, interval=0.02):
        """Block until ``predicate()`` is truthy.

        The device runs on its own thread, so anything the app writes arrives
        asynchronously: assert through this rather than immediately after the
        call that triggered the write.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return predicate()

    # ------------------------------------------------------- port discovery

    def port_info(self):
        """A ListPortInfo the app's scanner will accept as a candidate."""
        info = list_ports_common.ListPortInfo(self.port)
        info.name = os.path.basename(self.port)
        info.description = ""
        info.vid = DEFAULT_VID
        info.pid = DEFAULT_PID
        info.serial_number = None
        info.hwid = f"USB VID:PID={DEFAULT_VID:04X}:{DEFAULT_PID:04X}"
        return info

    @contextmanager
    def patch_comports(self, others=()):
        """Make ``list_ports.comports()`` report this device (and nothing real)."""
        ports = [self.port_info(), *others]
        with patch("serial.tools.list_ports.comports", return_value=ports):
            yield ports

    # ------------------------------------------------------------- transport

    def _read(self, count=4096, timeout=0.2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return b""
            try:
                chunk = os.read(self._master, count)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            except OSError:
                return b""
            if chunk:
                return chunk
        return b""

    def _write(self, data):
        view = memoryview(data)
        while view:
            try:
                written = os.write(self._master, view)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            except OSError as exc:
                self.errors.append(f"write failed: {exc}")
                return
            view = view[written:]

    # ---------------------------------------------------------- command loop

    _ZMODEM_PREFIX = bytes([ZPAD, ZPAD, ZDLE])

    def _serve(self):
        pending = bytearray()
        while not self._stop.is_set():
            chunk = self._read(timeout=0.1)
            if not chunk:
                continue
            pending += chunk

            # ZMODEM first: the receiver opens with ZRINIT headers, and those end
            # in "\r\n" too. Splitting on newlines before checking would consume
            # the header as a stray command line and stall the whole handshake.
            if self._ZMODEM_PREFIX in pending:
                self._run_zmodem_send(bytes(pending))
                pending = bytearray()
                continue

            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending = bytearray(rest)
                self._handle_command(line.strip())

    def _handle_command(self, line):
        if not line:
            return
        text = line.decode("ISO-8859-1", errors="replace")
        self.commands.append(text)

        if text.startswith("RQP+DEVICEINFO?"):
            if not self.respond_to_deviceinfo:
                return
            payload = {
                "deviceName": self.device_name,
                "serialNumber": self.serial_number,
            }
            self._write(json.dumps(payload).encode("utf-8") + b"\n")
        elif text.startswith("RQP+SETTIME="):
            self.timestamps.append(int(text.split("=", 1)[1]))

    # ------------------------------------------------------- ZMODEM sending

    def _run_zmodem_send(self, already_read=b""):
        """Act as the ZMODEM sender for one session."""
        try:
            self._rxbuf = bytearray()
            if not self._await_zrinit(already_read):
                self.errors.append("no ZRINIT from receiver")
                return

            remaining = list(self.profiles.items())
            while remaining:
                name, content = remaining.pop(0)
                self._send_file(name, content, files_left=len(remaining))
                self.files_sent.append(name)

            self._send_header(ZFIN, 0)
            self._await_header(kinds={ZFIN}, timeout=2)
            # "OO" ends the session; send it even if the ZFIN reply was missed,
            # otherwise the receiver sits in its read loop until it times out.
            self._write(b"OO")
        except Exception as exc:  # noqa: BLE001 - surfaced through .errors
            self.errors.append(f"zmodem send failed: {exc!r}")

    def _await_zrinit(self, already_read=b"", timeout=10):
        header = self._await_header(kinds={ZRINIT}, timeout=timeout, seed=already_read)
        return header is not None

    def _send_file(self, name, content, files_left):
        # ZFILE header, then a subpacket of "name\0size mtime_octal mode serial left"
        self._send_header(ZFILE, 0)
        mtime = int(time.time())
        meta = f"{len(content)} {mtime:o} 0 0 {files_left}".encode("ISO-8859-1")
        self._send_subpacket(name.encode("ISO-8859-1") + b"\x00" + meta + b"\x00", ZCRCW)

        # The receiver ACKs the offer, then sends ZRPOS to say where to start.
        header = self._await_header(kinds={ZRPOS}, timeout=10)
        if header is None:
            self.errors.append(f"no ZRPOS for {name!r}")
            return
        pos = self._header_pos(header)

        self._send_header(ZDATA, pos)
        payload = content[pos:]
        for offset in range(0, len(payload), SUBPACKET_SIZE):
            block = payload[offset : offset + SUBPACKET_SIZE]
            last = offset + SUBPACKET_SIZE >= len(payload)
            self._send_subpacket(block, ZCRCE if last else ZCRCG)
        if not payload:
            self._send_subpacket(b"", ZCRCE)

        self._send_header(ZEOF, len(content))

    # -------------------------------------------------------- framing (out)

    def _send_header(self, kind, pos):
        body = bytes(
            [
                kind,
                pos & 0xFF,
                (pos >> 8) & 0xFF,
                (pos >> 16) & 0xFF,
                (pos >> 24) & 0xFF,
            ]
        )
        crc = _crc16_bytes(body)
        frame = bytes([ZPAD, ZPAD, ZDLE, ZBIN])
        frame += _escape(body)
        frame += _escape(bytes([(crc >> 8) & 0xFF, crc & 0xFF]))
        self._write(frame)

    def _send_subpacket(self, data, terminator):
        crc = _crc16_bytes(data)
        crc = crc16(chr(terminator), crc)
        frame = _escape(data)
        frame += bytes([ZDLE, terminator])
        frame += _escape(bytes([(crc >> 8) & 0xFF, crc & 0xFF]))
        self._write(frame)

    # --------------------------------------------------------- framing (in)

    def _await_header(self, kinds, timeout=5, seed=b""):
        """Read until a header of one of ``kinds`` arrives. Returns its 5 bytes.

        Headers that are not of interest are consumed and skipped, so waiting for
        a ZRPOS transparently steps over the ZACK that precedes it.
        """
        if seed:
            self._rxbuf += seed
        deadline = time.monotonic() + timeout
        while True:
            header = self._extract_header()
            if header is not None:
                if header[0] in kinds:
                    return header
                continue
            if time.monotonic() >= deadline:
                return None
            chunk = self._read(timeout=0.05)
            if chunk:
                self._rxbuf += chunk

    def _extract_header(self):
        """Pull the first complete header out of the receive buffer.

        The receiver only ever sends hex headers (``_send_hex_header``), so that
        is the one form parsed here: ZPAD ZPAD ZDLE ZHEX, then 5 header bytes and
        a 2-byte CRC, all hex-encoded as 14 ASCII characters.
        """
        prefix = bytes([ZPAD, ZPAD, ZDLE, ZHEX])
        start = self._rxbuf.find(prefix)
        if start < 0:
            # No header yet. Keep a short tail in case a prefix straddles reads.
            if len(self._rxbuf) > len(prefix):
                del self._rxbuf[: -len(prefix)]
            return None
        body_at = start + len(prefix)
        if len(self._rxbuf) - body_at < 14:
            del self._rxbuf[:start]  # incomplete; wait for the rest
            return None
        try:
            decoded = bytes.fromhex(self._rxbuf[body_at : body_at + 14].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            del self._rxbuf[:body_at]  # malformed; skip past this prefix
            return None
        del self._rxbuf[: body_at + 14]
        return decoded[:5]

    @staticmethod
    def _header_pos(header):
        return (
            header[1] | header[2] << 8 | header[3] << 16 | header[4] << 24
        )
