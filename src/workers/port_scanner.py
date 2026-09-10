"""
Device discovery: finding RQP Live units on the serial ports, by itself.

There used to be one scan: open every candidate port in a thread pool, wait
for all of them, then show the list. On Windows that wait is the Bluetooth
page timeout, 5.12 s, for every paired unit that happens to be off, and the
radio pages one unit at a time, so the thread pool bought nothing and the
list stayed empty until the slowest port had given up.

What runs now is a lane: one background thread that keeps a table of the
ports, re-reads the port list every second or two (cheap), and probes one
port at a time in priority order. A USB port is probed the moment it
appears. A Bluetooth port is probed on a cadence that depends on how recently
the paired unit was used, back to back while an operator is likely to be
switching one on, and rarely for pairings nobody has touched in weeks. Every
probe publishes its own result, so a unit that answers is listed a second
after it is asked, whatever else is still being paged.

Pressing the scan button does not change what the lane can do, only the
order and the urgency: it marks every candidate for one pass, most likely
unit first, drops every backoff, and keeps the lane eager for a while. The
status bar shows that pass and can stop it; the lane goes on quietly after.

Three things the measurements settled, and the code leans on:
- A page cannot be cancelled. A blocked open returns when Windows lets it,
  so stopping means "after this probe", never mid-probe.
- The radio serialises pages. Probing two absent units in parallel takes
  twice as long, so there is exactly one prober, and the RQFT connection
  workers do not page Bluetooth ports themselves: they wait for the lane
  to report the unit reachable (see workers.device_connection).
- Paging while another unit's link is open costs that link about a third of
  its throughput. The lane pauses for the duration of a sync.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal
from serial.tools import list_ports_common

import settings
from models.SerialPort import SerialPortItem, natural_sort_key
from utils import preferences
from utils.bluetooth_ports import (
    KIND_BLUETOOTH,
    KIND_BLUETOOTH_INCOMING,
    KIND_OTHER,
    KIND_USB,
    classify_port,
    matches_bluetooth_marker,
    paired_devices,
    split_paired_name,
)
from utils.rqft_support import parse_firmware_version
from utils.serial_errors import CAUSE_HELD, classify_port_error
from utils.time_sync import send_timestamp
from utils.translation import _

log = logging.getLogger(__name__)

# How long a probed unit gets to answer DEVICEINFO once the port is open.
# A unit that is on answers within a few tens of milliseconds, but a
# Bluetooth round trip right after the link comes up was measured at up to
# 0.2 s, and a probe that gives up then reports a live unit as silent.
PROBE_READ_TIMEOUT_S = 1.0
PROBE_WRITE_TIMEOUT_S = 0.2


# -- one probe ---------------------------------------------------------------

def probe_port(port_info, running=lambda: True):
    """Ask one port whether an RQP Live is behind it.

    Opens the port, sends RQP+DEVICEINFO?, and reads one line. A unit that
    answers gets its clock set on the way out. Returns
    ``(port_info, device_responded, error_message)``; the port_info carries
    the description, serial number and firmware version the unit reported.

    ``running`` is consulted after the open: an open on a Bluetooth port can
    block for seconds, and a shutdown that arrived meanwhile should not send
    anything.
    """
    if not running():
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
            timeout=PROBE_READ_TIMEOUT_S,
            write_timeout=PROBE_WRITE_TIMEOUT_S,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        if not running():
            return port_info, False, "Scan cancelled"

        port.write(b"RQP+DEVICEINFO?\n")
        # errors="replace": a byte the device did not mean to send is a
        # line that will not parse, not a probe that raises. A freshly
        # opened Bluetooth link delivers one now and then, and a strict
        # decode threw UnicodeDecodeError past the handler below — which
        # catches OSError and not that — so a live unit was greyed out
        # over a single corrupted byte.
        response = port.readline().decode("utf-8", errors="replace").strip()

        if running() and response:
            log.debug(f"Port {port_info.device} response: {response}")
            try:
                response_data = json.loads(response)
                if (
                    "deviceName" in response_data
                    and "serialNumber" in response_data
                ):
                    port_info.description = response_data["deviceName"]
                    port_info.serial_number = response_data["serialNumber"]
                    port_info.firmware_version = response_data.get(
                        "firmwareVersion", ""
                    )
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


# -- which ports are worth asking --------------------------------------------

def _coerce_id(value):
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


def _allowed_usb_ids():
    return {
        (_coerce_id(vid), _coerce_id(pid))
        for vid, pid in getattr(settings, "ALLOWED_SERIAL_USB_IDS", set())
    }


def matches_allowed_usb_id(port_info):
    vid = getattr(port_info, "vid", None)
    pid = getattr(port_info, "pid", None)
    if vid is None or pid is None:
        return False
    return (int(vid), int(pid)) in _allowed_usb_ids()


def should_probe_port(port_info, port_class):
    """Whether a port is a candidate at all.

    Pinned ports always are: pinning is the operator saying "this one".
    Otherwise a port has to look like the unit's USB interface or like a
    Bluetooth port. An incoming Bluetooth port never has a unit behind it,
    RollView is the side that calls, so it is left alone.
    """
    if port_info.device in preferences.pinned_serial_ports:
        return True
    if port_class.kind == KIND_BLUETOOTH_INCOMING:
        return False
    return (
        matches_allowed_usb_id(port_info)
        or port_class.kind == KIND_BLUETOOTH
        or matches_bluetooth_marker(
            port_info, getattr(settings, "SERIAL_BLUETOOTH_PORT_MARKERS", ())
        )
    )


def _port_info(device):
    """A bare ListPortInfo for a device name.

    Without skip_link_detection pyserial asks os.path.islink() about the
    name, and Windows answers that by opening the device: a second of link
    set-up for a unit that is on, a page for one that is off. pyserial's
    own enumerator skips the check for the same reason.
    """
    return list_ports_common.ListPortInfo(device, skip_link_detection=True)


# -- the table -----------------------------------------------------------------

@dataclass
class Candidate:
    """One port the lane knows about. Mutated only under the lane's lock."""
    device: str
    info: list_ports_common.ListPortInfo
    kind: str
    address: Optional[str] = None
    probeable: bool = False
    pinned: bool = False
    paired_name: str = ""
    last_used: Optional[float] = None      # wall clock, from the paired list
    # None until probed; then whether the last probe was answered.
    reachable: Optional[bool] = None
    # Why the last probe was not answered: a utils.serial_errors cause.
    error_cause: Optional[str] = None
    # Monotonic clock throughout.
    last_probe: float = 0.0
    responded_at: float = 0.0
    next_due: float = 0.0
    requested_at: Optional[float] = None    # an explicit "this one next"
    in_pass: bool = False
    # (description, serial number, firmware version) the unit last reported.
    identity: Optional[tuple] = None


class DiscoveryLane:
    """The background thread that keeps the port table and probes it.

    Results go out through ``publisher``, an object with the methods
    ``port_appeared(item)``, ``port_gone(device)``, ``port_result(item)``,
    ``progress(percent, text)`` and ``pass_finished(items)``. They are called
    from the lane thread, except that ``stop_pass`` reports from its caller.

    Everything time-related takes an injected clock so the ordering rules
    can be tested without waiting; ``step()`` is one unit of work and can be
    driven by hand.
    """

    def __init__(
        self,
        publisher,
        busy_ports: Optional[Callable[[], dict]] = None,
        clock=time.monotonic,
        wall_clock=time.time,
        comports=None,
        paired=None,
        probe=None,
    ):
        self._publisher = publisher
        self._busy_ports = busy_ports or (lambda: {})
        self._clock = clock
        self._wall_clock = wall_clock
        # Looked up when they are called, not bound here: the lane outlives
        # the window's construction, and a test that patches the port list
        # afterwards — which is how the fake device is put in front of it —
        # would otherwise be talking to a name this object stopped reading.
        self._comports = comports or (lambda: serial.tools.list_ports.comports())
        self._paired = paired or (lambda: paired_devices())
        self._probe = probe or (lambda *args: probe_port(*args))

        self._cond = threading.Condition(threading.RLock())
        self._cands: dict[str, Candidate] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._paused = False
        self._current: Optional[str] = None
        self._preferred: Optional[str] = None
        self._next_enum = 0.0
        self._radio_free_at = 0.0
        self._eager_until = 0.0
        self._pass_requested = False
        self._pass_active = False
        self._pass_total = 0
        self._pass_done = 0

    # -- publishing ----------------------------------------------------

    def _publish(self, event, *args):
        """Hand an event to the publisher.

        A shutdown that times out on a Bluetooth page leaves this thread
        alive after the widget is gone; emitting on a deleted QObject then
        raises here, in the wrong thread to do anything about it. The
        event is dropped, since nobody is left to hear it.
        """
        try:
            getattr(self._publisher, event)(*args)
        except RuntimeError as error:
            log.debug(f"Discovery event {event} dropped: {error}")

    # -- lifecycle (any thread) ----------------------------------------

    def start(self):
        """Start the thread; a no-op while it runs. A lane stopped earlier
        can be started again."""
        with self._cond:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="device-discovery", daemon=True
            )
            self._thread.start()

    def is_alive(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def request_stop(self):
        """Ask the thread to exit after the probe it is in, if any."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()

    def join(self, timeout=None):
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout)

    # -- requests (GUI thread) -----------------------------------------

    def scan_now(self):
        """One pass over every candidate, most likely first, and eager
        probing for a while after. The lane enumerates first, so a pass
        asked for before the first enumeration still covers every port."""
        with self._cond:
            self._pass_requested = True
            self._eager_until = self._clock() + settings.DISCOVERY_EAGER_S
            self._cond.notify_all()

    def stop_pass(self):
        """End the pass, and the eager window with it: the operator asked
        for the radio to be left alone. Recently used units are still
        probed on their own cadence. Reports pass_finished from the
        caller's thread, and only once, whichever side gets there first."""
        with self._cond:
            self._pass_requested = False
            self._eager_until = 0.0
            now = self._clock()
            for candidate in self._cands.values():
                # A stale pairing already asked once goes back to its slow
                # cadence at once, not after the re-probe the eager window
                # had scheduled. One never asked is still asked once.
                if (
                    candidate.kind == KIND_BLUETOOTH
                    and candidate.reachable is False
                    and not self._is_recent_locked(candidate)
                ):
                    candidate.next_due = max(
                        candidate.next_due, now + settings.DISCOVERY_STALE_INTERVAL_S
                    )
            ended = self._end_pass_locked()
            items = self._items_locked() if ended else None
        if ended:
            self._publish("pass_finished", items)

    def probe_now(self, device):
        """Probe this port before anything else that is waiting."""
        with self._cond:
            candidate = self._cands.get(device)
            if candidate is None:
                log.info(f"No such port to probe: {device}")
                return False
            candidate.requested_at = self._clock()
            candidate.next_due = 0.0
            self._cond.notify_all()
        return True

    def set_paused(self, paused):
        """Hold off probing, for the duration of a sync. The probe in
        flight completes; nothing new starts until unpaused."""
        with self._cond:
            self._paused = bool(paused)
            self._cond.notify_all()

    def set_preferred(self, device):
        """The port the operator has selected goes first in every order."""
        with self._cond:
            self._preferred = device

    def current_probe(self):
        with self._cond:
            return self._current

    def wait_until_port_free(self, device, timeout):
        """Block until the lane is not inside a probe of this port.

        For a sync about to open the port itself. Bounded: a unit that is
        on answers in about a second, and one that is not would fail the
        sync's own open anyway.
        """
        deadline = self._clock() + timeout
        with self._cond:
            while self._current == device:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                self._cond.wait(min(remaining, 0.1))
        return True

    def snapshot(self):
        """Every known port as an item, for a pass summary."""
        with self._cond:
            return self._items_locked()

    # -- the thread ----------------------------------------------------

    def _run(self):
        log.info("Device discovery started")
        while not self._stop.is_set():
            try:
                worked = self.step()
            except Exception:
                # The lane is the only thing that finds devices; one bad
                # port or one odd enumeration must not end it.
                log.exception("Device discovery step failed")
                worked = False
                time.sleep(0.5)
            if worked or self._stop.is_set():
                continue
            with self._cond:
                if not self._stop.is_set():
                    self._cond.wait(self._idle_wait_locked())
        log.info("Device discovery stopped")

    def step(self):
        """One unit of work: enumerate if due, then run the next probe.
        Returns True when a probe ran."""
        if self._stop.is_set():
            return False
        with self._cond:
            pass_requested = self._pass_requested
            enumerate_due = self._clock() >= self._next_enum
        if pass_requested or enumerate_due:
            self._refresh()
        if pass_requested:
            self._begin_pass()
        busy = self._busy_snapshot()
        with self._cond:
            if self._paused or self._stop.is_set():
                return False
            candidate = self._pick_next_locked(busy)
            if candidate is None:
                self._finish_pass_if_done_locked(busy)
                return False
            self._current = candidate.device
            info = candidate.info
            device = candidate.device
            kind = candidate.kind
            starting = (self._pass_progress_locked(device)
                        if self._pass_active and candidate.in_pass else None)
        if starting is not None:
            self._publish("progress", *starting)
        self._run_probe(device, info, kind)
        return True

    def _idle_wait_locked(self):
        """How long to sleep with nothing to do: until the next enumeration
        or the next due probe, whichever is sooner, and never a busy loop."""
        now = self._clock()
        wake = self._next_enum
        if not self._paused:
            for candidate in self._cands.values():
                if not candidate.probeable:
                    continue
                due = candidate.next_due
                if candidate.kind == KIND_BLUETOOTH:
                    due = max(due, self._radio_free_at)
                wake = min(wake, due)
        return min(max(wake - now, 0.05), settings.DISCOVERY_ENUMERATE_INTERVAL_S)

    def _busy_snapshot(self):
        try:
            return dict(self._busy_ports() or {})
        except Exception:
            log.exception("Busy port lookup failed; probing nothing this step")
            # Safer to probe nothing than to inject into a live session.
            return {device: None for device in list(self._cands)}

    # -- enumeration ---------------------------------------------------

    def _refresh(self):
        """Re-read the port list and reconcile the table with it."""
        try:
            ports = list(self._comports())
        except Exception:
            log.exception("Listing the serial ports failed")
            with self._cond:
                self._next_enum = self._clock() + settings.DISCOVERY_ENUMERATE_INTERVAL_S
            return
        pinned = set(preferences.pinned_serial_ports)
        seen = {port.device for port in ports}
        for device in sorted(pinned - seen, key=natural_sort_key):
            info = _port_info(device)
            info.description = ""
            info.serial_number = ""
            ports.append(info)
        try:
            paired = self._paired() or {}
        except Exception:
            log.exception("Paired device lookup failed")
            paired = {}

        # Ports a connection worker holds are listed from what the worker
        # knows, the way a pass reports them: a port back after a replug
        # is that unit, and a session coming up on it is the row changing.
        busy = self._busy_snapshot()
        appeared = []
        updated = []
        gone = []
        with self._cond:
            now = self._clock()
            present = {port.device for port in ports}
            for device in list(self._cands):
                if device not in present:
                    # A probe in flight on it fails on its own and finds
                    # no candidate to record against.
                    gone.append(device)
                    del self._cands[device]
            for port in ports:
                status = busy.get(port.device) if port.device in busy else None
                candidate = self._cands.get(port.device)
                if candidate is None:
                    candidate = self._new_candidate_locked(port, pinned, paired, now)
                    self._cands[port.device] = candidate
                    if status is not None:
                        self._adopt_worker_status_locked(candidate, status)
                    appeared.append(
                        self._item_locked(candidate, known_device=status is not None)
                    )
                    continue
                changed = self._update_candidate_locked(candidate, port, pinned, paired)
                if status is not None and self._adopt_worker_status_locked(candidate, status):
                    changed = True
                if changed:
                    # Pinned, newly named from the paired list, or its
                    # worker's session came up or went: the row reads
                    # differently, so it goes out again.
                    updated.append(
                        self._item_locked(candidate, known_device=status is not None)
                    )
            self._next_enum = now + settings.DISCOVERY_ENUMERATE_INTERVAL_S
        for item in appeared:
            self._publish("port_appeared", item)
        for item in updated:
            self._publish("port_result", item)
        for device in gone:
            self._publish("port_gone", device)

    def _adopt_worker_status_locked(self, candidate, status):
        """Take what a connection worker knows about its port. Returns
        whether the row now reads differently.

        Every field falls back to what the last probe learned. A worker
        started before any DEVICEINFO answer carries a blank identity, and
        overwriting the firmware version with it dropped the unit's RQFT
        capability on the next pass.
        """
        before = (candidate.identity, candidate.reachable)
        identity = status.identity
        known = candidate.identity or ("", "", "")
        candidate.identity = (
            identity.device_name or known[0],
            identity.serial_number or known[1],
            identity.firmware_version or known[2],
        )
        candidate.reachable = bool(status.connected)
        return (candidate.identity, candidate.reachable) != before

    def _new_candidate_locked(self, port, pinned, paired, now):
        markers = getattr(settings, "SERIAL_BLUETOOTH_PORT_MARKERS", ())
        port_class = classify_port(port, markers)
        candidate = Candidate(
            device=port.device,
            info=port,
            kind=port_class.kind,
            address=port_class.address,
        )
        self._update_candidate_locked(candidate, port, pinned, paired)
        # New ports are asked straight away: a USB unit was just plugged in,
        # and a Bluetooth port seen for the first time is the start-up pass.
        candidate.next_due = now
        return candidate

    def _update_candidate_locked(self, candidate, port, pinned, paired):
        """Bring a candidate up to date with this enumeration. Returns
        whether anything the list shows about it changed."""
        before = (candidate.pinned, candidate.paired_name, candidate.probeable)
        candidate.info = port
        candidate.pinned = port.device in pinned
        markers = getattr(settings, "SERIAL_BLUETOOTH_PORT_MARKERS", ())
        port_class = classify_port(port, markers)
        candidate.kind = port_class.kind
        candidate.address = port_class.address
        candidate.probeable = should_probe_port(port, port_class)
        device = paired.get(candidate.address) if candidate.address else None
        if device is not None:
            candidate.paired_name = device.name or ""
            candidate.last_used = device.last_used
        return (candidate.pinned, candidate.paired_name, candidate.probeable) != before

    # -- ordering ------------------------------------------------------

    def _is_recent_locked(self, candidate):
        if candidate.responded_at > 0:
            return True
        if candidate.last_used is None:
            return False
        age_days = (self._wall_clock() - candidate.last_used) / 86400.0
        return age_days <= settings.DISCOVERY_RECENT_DAYS

    def _priority_locked(self, candidate):
        """Lower sorts first. The port the operator is looking at; then
        instant opens before pages; then pinned ports, units that answered
        this session, recently used pairings, the rest."""
        preferred = 0 if candidate.device == self._preferred else 1
        instant = 0 if candidate.kind in (KIND_USB, KIND_OTHER) else 1
        if candidate.pinned:
            tier = 0
        elif candidate.responded_at > 0:
            tier = 1
        elif self._is_recent_locked(candidate):
            tier = 2
        else:
            tier = 3
        recency = max(candidate.responded_at, candidate.last_used or 0.0)
        return (preferred, instant, tier, -recency, natural_sort_key(candidate.device))

    def _eligible_locked(self, busy, now):
        radio_free = now >= self._radio_free_at
        for candidate in self._cands.values():
            if not candidate.probeable:
                continue
            if candidate.device in busy:
                # Held by a connection worker, which knows better than a
                # probe would. Look again later rather than every tick.
                if candidate.next_due <= now:
                    candidate.next_due = now + settings.DISCOVERY_LIVE_RECHECK_INTERVAL_S
                continue
            if candidate.kind == KIND_BLUETOOTH and not radio_free:
                continue
            yield candidate

    def _pick_next_locked(self, busy):
        now = self._clock()
        eligible = list(self._eligible_locked(busy, now))
        requested = [c for c in eligible if c.requested_at is not None]
        if requested:
            return min(requested, key=lambda c: c.requested_at)
        in_pass = [c for c in eligible if c.in_pass]
        if in_pass:
            return min(in_pass, key=self._priority_locked)
        due = [c for c in eligible if c.next_due <= now]
        if due:
            # Background probing is first come, first served, with priority
            # only splitting ties. Priority alone would let a recently used
            # unit that is off, probed back to back, keep a stale one from
            # ever getting the turn it was due.
            return min(due, key=lambda c: (c.next_due, self._priority_locked(c)))
        return None

    def _next_due_locked(self, candidate, now):
        if candidate.reachable:
            return now + settings.DISCOVERY_LIVE_RECHECK_INTERVAL_S
        if candidate.error_cause == CAUSE_HELD:
            # Another program has the port. The open fails at once, no
            # paging, so asking again soon costs nothing and notices the
            # port being let go.
            return now + settings.DISCOVERY_RETRY_INTERVAL_S
        if candidate.kind == KIND_BLUETOOTH:
            if now < self._eager_until or self._is_recent_locked(candidate):
                return now + settings.DISCOVERY_BLUETOOTH_GAP_S
            return now + settings.DISCOVERY_STALE_INTERVAL_S
        return now + settings.DISCOVERY_RETRY_INTERVAL_S

    # -- probing -------------------------------------------------------

    def _identity_locked(self, candidate, port_info):
        """What the unit is, after a probe it answered.

        Almost always just what it said. The exception is the firmware
        version, which decides whether the unit gets a persistent RQFT
        connection or the legacy sync path: a version that will not parse is
        not evidence that the unit is old, only that this answer cannot be
        read, and one corrupted byte inside the string is enough for that.
        The line still parses as JSON, so it is not lost the way a mangled
        one is -- it is read, believed, and a unit already known to speak
        RQFT is written down as legacy.

        So an unreadable version leaves a readable one alone, for as long as
        the serial number says it is the same unit. A version that parses is
        always taken, including one below the minimum: a unit really can be
        downgraded, and that is what saying so looks like.
        """
        description = port_info.description
        serial_number = port_info.serial_number
        firmware = getattr(port_info, "firmware_version", "") or ""
        known = candidate.identity
        if (
            known is not None
            and parse_firmware_version(firmware) is None
            and parse_firmware_version(known[2]) is not None
            and serial_number == known[1]
        ):
            log.debug(
                f"{candidate.device} reported an unreadable firmware version "
                f"{firmware!r}; keeping {known[2]!r}"
            )
            firmware = known[2]
        return (description, serial_number, firmware)

    def _run_probe(self, device, info, kind):
        running = lambda: not self._stop.is_set()  # noqa: E731
        try:
            port_info, responded, error = self._probe(info, running)
        except Exception as e:
            log.exception(f"Probe of {device} failed")
            port_info, responded, error = info, False, str(e)
        cancelled = error == "Scan cancelled"
        if error and not cancelled:
            log.debug(f"Port {device} probe: {error}")

        with self._cond:
            now = self._clock()
            if kind == KIND_BLUETOOTH:
                self._radio_free_at = now + settings.DISCOVERY_BLUETOOTH_GAP_S
            candidate = self._cands.get(device)
            item = None
            if candidate is not None and not cancelled:
                candidate.reachable = bool(responded)
                candidate.last_probe = now
                candidate.requested_at = None
                candidate.error_cause = None if responded else classify_port_error(error)
                if responded:
                    candidate.responded_at = now
                    candidate.identity = self._identity_locked(candidate, port_info)
                candidate.next_due = self._next_due_locked(candidate, now)
                item = self._item_locked(candidate)
                if candidate.in_pass:
                    candidate.in_pass = False
                    if self._pass_active:
                        # Counted here, reported as the next probe opens: see
                        # _pass_progress_locked.
                        self._pass_done += 1
            self._current = None
            self._cond.notify_all()

        if item is not None:
            self._publish("port_result", item)
        busy = self._busy_snapshot()
        with self._cond:
            self._finish_pass_if_done_locked(busy)

    # -- passes --------------------------------------------------------

    def _begin_pass(self):
        busy = self._busy_snapshot()
        cached = []
        with self._cond:
            if not self._pass_requested:
                return
            self._pass_requested = False
            total = 0
            for candidate in self._cands.values():
                status = busy.get(candidate.device)
                if candidate.device in busy:
                    # Held by a connection worker: reported from what it
                    # knows, never probed. Probing would inject bytes into
                    # a live session.
                    candidate.in_pass = False
                    if status is not None:
                        self._adopt_worker_status_locked(candidate, status)
                        cached.append(self._item_locked(candidate, known_device=True))
                    continue
                if not candidate.probeable:
                    continue
                candidate.in_pass = True
                candidate.next_due = 0.0
                total += 1
            self._pass_active = True
            self._pass_total = total
            self._pass_done = 0
            log.info(f"Device scan: {total} ports to probe")
        for item in cached:
            self._publish("port_result", item)
        if total == 0:
            self._publish("progress", 100, _("PORTSCAN_COMPLETE_TEXT"))
            with self._cond:
                self._finish_pass_if_done_locked(busy)

    def _pass_progress_locked(self, device):
        """How far the pass has got, and which port it is on.

        Said as a probe opens rather than as one closes. A Bluetooth page
        takes about five seconds, so a row that names the port it has just
        finished with has nothing to say for the whole of the one it is
        working on: the scan starts, and the status row holds "scanning for
        devices" and a bar at zero until the first port is already behind it.
        Worse, that first port's line is replaced the moment the second one
        finishes, which on a machine whose ports answer quickly is before
        anybody has read it — the first port an operator sees named is the
        second one.

        The bar counts what is done; the words name what is being done now.
        """
        percent = int(self._pass_done * 100 / max(self._pass_total, 1))
        text = (f"{_('PORTSCAN_SCANNING_PORT_TEXT')} '{device}'... "
                f"({self._pass_done + 1}/{self._pass_total})")
        return percent, text

    def _finish_pass_if_done_locked(self, busy):
        """End the pass once nothing marked for it can still be probed.
        A candidate that became busy mid-pass (a worker took it) counts as
        done; one that vanished is gone from the table already."""
        if not self._pass_active:
            return
        for candidate in self._cands.values():
            if candidate.in_pass and candidate.device in busy:
                candidate.in_pass = False
            if candidate.in_pass and candidate.probeable:
                return
        if self._end_pass_locked():
            items = self._items_locked()
            self._publish("pass_finished", items)

    def _end_pass_locked(self):
        if not self._pass_active:
            return False
        self._pass_active = False
        for candidate in self._cands.values():
            candidate.in_pass = False
        return True

    # -- items ---------------------------------------------------------

    def _item_locked(self, candidate, known_device=False):
        info = _port_info(candidate.device)
        source = candidate.info
        for attr in ("hwid", "vid", "pid", "manufacturer", "product", "name"):
            setattr(info, attr, getattr(source, attr, None))
        firmware = ""
        if candidate.identity is not None:
            info.description, info.serial_number, firmware = candidate.identity
        elif candidate.paired_name:
            info.description, info.serial_number = split_paired_name(candidate.paired_name)
        else:
            info.description = source.description
            info.serial_number = source.serial_number
        info.firmware_version = firmware
        item = SerialPortItem(
            info,
            device_responded=bool(candidate.reachable),
            known_device=known_device,
            reachable=candidate.reachable,
            paired_name=candidate.paired_name,
            transport=candidate.kind,
            bluetooth_address=candidate.address,
            error_cause=candidate.error_cause,
        )
        return item

    def _items_locked(self):
        return [
            self._item_locked(candidate)
            for candidate in sorted(
                self._cands.values(), key=lambda c: natural_sort_key(c.device)
            )
        ]


# -- the Qt face ---------------------------------------------------------------

class _SignalPublisher:
    """The lane's publisher, turning each event into one of the scanner's
    signals. A separate object rather than the scanner itself: a Qt signal
    attribute is not callable, so the scanner cannot double as the
    publisher under the same names."""

    def __init__(self, scanner):
        self._scanner = scanner

    def port_appeared(self, item):
        self._scanner.port_appeared.emit(item)

    def port_gone(self, device):
        self._scanner.port_gone.emit(device)

    def port_result(self, item):
        self._scanner.port_result.emit(item)

    def progress(self, percent, text):
        self._scanner.progress.emit(percent, text)

    def pass_finished(self, items):
        self._scanner.finished.emit(list(items))


class PortScanner(QObject):
    """The discovery lane as the GUI sees it: signals in, requests out.

    Signals are emitted from the lane thread and delivered queued to the
    widget; ``finished`` is also emitted from the GUI thread when the
    operator stops a pass.
    """

    progress = Signal(int, str)
    finished = Signal(list)          # a pass ended: every known port
    port_appeared = Signal(object)   # SerialPortItem, before any probe
    port_gone = Signal(str)          # device name
    port_result = Signal(object)     # SerialPortItem, after a probe

    def __init__(self, parent=None, busy_ports=None):
        super().__init__(parent)
        self._lane = DiscoveryLane(
            publisher=_SignalPublisher(self), busy_ports=busy_ports
        )

    # -- requests ------------------------------------------------------

    def set_busy_ports_provider(self, provider):
        """A callable returning {device: BusyPortStatus} for the ports a
        connection worker holds. Called from the lane thread, so it must
        only read."""
        self._lane._busy_ports = provider or (lambda: {})

    def start(self):
        self._lane.start()

    def scan_now(self):
        """The scan button and start-up: one eager pass, most likely first.

        The request is recorded before the thread starts, so its first
        step is the pass rather than a first-sight probe of the same
        ports followed by the pass asking them again."""
        self._lane.scan_now()
        self._lane.start()

    def probe_port(self, device):
        """The Connect action on one unit: that port next."""
        self._lane.start()
        return self._lane.probe_now(device)

    def request_stop(self):
        """The status bar's Stop: end the pass. The lane keeps going
        quietly; a probe in flight completes, since nothing can cut a
        Bluetooth page short."""
        self._lane.stop_pass()

    def request_shutdown(self):
        """Ask the lane to stop for good, and return at once.

        For closing the window. Nothing in Qt requires waiting for this
        thread — it is a plain daemon, not a QThread — and its one
        resource is a serial port the operating system reclaims. Since a
        probe inside a Bluetooth page cannot be cut short, waiting for it
        kept the window on screen for a whole page, five seconds, after
        the operator had asked for it to go.
        """
        self._lane.stop_pass()
        self._lane.request_stop()

    def set_paused(self, paused):
        self._lane.set_paused(paused)

    def set_preferred(self, device):
        self._lane.set_preferred(device)

    def wait_until_port_free(self, device, timeout_s=2.0):
        return self._lane.wait_until_port_free(device, timeout_s)

    def is_running(self):
        return self._lane.is_alive()

    def stop(self, timeout_ms=6000):
        """Shutdown: stop the thread and wait for it.

        Returns True if it was not running or exited within the timeout.
        The wait can be a whole Bluetooth page, 5.12 s, when one has just
        started, so the default allows for one; the thread is a daemon, so
        a page that outlives the timeout ends with the process.
        """
        self._lane.stop_pass()
        self._lane.request_stop()
        if not self._lane.is_alive():
            return True
        log.info("Stopping device discovery")
        self._lane.join(timeout_ms / 1000.0)
        return not self._lane.is_alive()
