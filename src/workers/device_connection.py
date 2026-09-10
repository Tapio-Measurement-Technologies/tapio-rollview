"""
Persistent RQFT device connections.

Each RQFT-capable device gets a DeviceConnectionWorker: a plain daemon
thread that is the sole owner of the serial transport and the sans-io
Session (driven by BlockingSessionDriver). Between operations the worker
pumps the session so keepalive PINGs flow and a device-initiated doorbell
HELLO is answered. All GUI communication crosses through ConnectionBridge
Qt signals (queued cross-thread delivery).

DeviceConnectionManager lives in the GUI thread and owns the workers and
the auto-connect policy. When a sync happens is the device's decision: it
schedules its own and asks for one with a NOTIFY.
"""
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

import settings
import store
from rqft.client import BlockingSessionDriver, LocalDirFs
from rqft.events import (
    DelDone,
    Ended,
    EntryListed,
    EntrySkipped,
    Established,
    GetDone,
    ListDone,
    NotifyReceived,
    OpFailed,
    Passthrough,
)
from rqft.link import AbortReason
from rqft.messages import (
    CAP_ALLOW_DELETE,
    NOTIFY_DELETE_AFTER_SYNC,
    NOTIFY_SYNC_INCREMENTAL,
    ErrCode,
    Role,
)
from utils.serial_transport import SteadySerialTransport
from rqft.session import Session, SessionState
from utils import preferences
from utils.rqft_support import (
    BusyPortStatus,
    DeviceIdentity,
    is_syncable_folder,
    is_syncable_prof,
    plan_device_deletes,
)
from utils.serial_errors import CAUSE_LINK_LOST, classify_port_error, describe_port_error
from utils.time_sync import device_wall_clock_to_epoch
from utils.translation import _

log = logging.getLogger(__name__)

# Transport read chunk used by the worker loop.
_READ_SIZE = 65536

# LIST_ENTRY type byte (SPEC.md section 5.3): 0 is a file, and the device
# reports its folders with a type of their own.
_ETYPE_FILE = 0

# Idle watchdog for one operation: no event, byte, or progress movement
# for this long fails the operation. The session's own T_DEAD (10 s)
# normally fires first.
_OP_IDLE_TIMEOUT_S = 15.0

# Minimum interval between fileByteProgress emissions per file.
_PROGRESS_EMIT_INTERVAL_S = 0.1

# Translation keys for SPEC.md section 5.3 error codes.
ERR_MESSAGE_KEYS = {
    ErrCode.E_FS_OPEN: "RQFT_ERR_FS_OPEN",
    ErrCode.E_FS_READ: "RQFT_ERR_FS_READ",
    ErrCode.E_FS_WRITE: "RQFT_ERR_FS_WRITE",
    ErrCode.E_FS_REMOVE: "RQFT_ERR_FS_REMOVE",
    ErrCode.E_PATH: "RQFT_ERR_PATH",
    ErrCode.E_CRC_FILE: "RQFT_ERR_CRC_FILE",
    ErrCode.E_TOO_LARGE: "RQFT_ERR_TOO_LARGE",
    ErrCode.E_DENIED: "RQFT_ERR_DENIED",
    ErrCode.E_BAD_STATE: "RQFT_ERR_BAD_STATE",
    ErrCode.E_UNSUPPORTED: "RQFT_ERR_UNSUPPORTED",
}


class ConnectionState(Enum):
    """User-visible state of one device connection."""
    DISABLED = "disabled"
    OPEN_BACKOFF = "open_backoff"
    LISTENING = "listening"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass
class SyncError:
    """One failed sync operation, mapped for user presentation.

    kind: busy | cancelled | op | transport | timeout | ended
    """
    kind: str
    message: str = ""
    err_code: Optional[ErrCode] = None
    path: Optional[str] = None
    fetched: list = field(default_factory=list)
    # transport only: the port had opened before it failed, so the cause
    # is a lost link rather than a port that could not be opened.
    opened: bool = False


def describe_sync_error(error: SyncError, port: str = "", unit_name: str = "") -> str:
    """Build a translated user-facing message for a failed sync."""
    if error.kind == "busy":
        return _("DEVICE_BUSY_STATUS")
    if error.kind == "transport":
        return describe_port_error(
            error.message, port, unit_name, opened=error.opened
        ).body
    if error.kind == "timeout":
        return _("SYNC_ERROR_TIMEOUT")
    if error.kind == "ended":
        return f"{_('SYNC_ERROR_ENDED')} {error.message}".strip()
    if error.kind == "op":
        hint = _(ERR_MESSAGE_KEYS[error.err_code]) if error.err_code in ERR_MESSAGE_KEYS else ""
        where = f" '{error.path}'" if error.path else ""
        return f"{_('SYNC_ERROR_OPERATION')}{where}: {hint or error.message}"
    return error.message


def sync_error_title(error: SyncError) -> str:
    """The message box title for a failed sync: the cause, for a port
    failure, and otherwise that the sync failed."""
    if error.kind == "transport":
        return describe_port_error(error.message, "", opened=error.opened).title
    return _("SYNC_FAILED_TITLE")


class ConnectionBridge(QObject):
    """The single Qt crossing point for one worker thread.

    Created in the GUI thread; the worker only calls signal.emit(), which
    Qt delivers as queued cross-thread calls.
    """
    stateChanged = Signal(str, object)          # port, ConnectionState
    established = Signal(str, bool)             # port, by_doorbell
    notify = Signal(str, int)                   # port, NOTIFY flags
    connectionLost = Signal(str, str)           # port, busy|dead|unplugged|closed|cancelled
    syncStarted = Signal(str, int, int)         # port, nfiles, nbytes
    receivingFile = Signal(str, int)            # path, files_left (countdown)
    fileByteProgress = Signal(int, int)         # current file: done, total
    syncFinished = Signal(str, list, int, int)  # port, fetched paths, skipped, deleted
    syncFailed = Signal(str, object)            # port, SyncError
    listWarnings = Signal(str, int)             # port, skipped unreadable entries


class _Cancelled(Exception):
    pass


class _OpTimeout(Exception):
    pass


class _SessionEnded(Exception):
    def __init__(self, event: Ended):
        self.event = event
        super().__init__(f"session ended with {event.reason.name} from_peer={event.from_peer}")


class _OperationFailed(Exception):
    def __init__(self, event: OpFailed):
        self.event = event
        super().__init__(f"{event.request.name} '{event.path}' failed: {event.code.name}")


@dataclass
class _Op:
    kind: str          # "check" | "sync" | "disconnect"
    auto: bool = False


class DeviceConnectionWorker(threading.Thread):
    """Owns the serial transport and Session for one device; sole thread
    touching either. Non-blocking public API for the GUI thread."""

    def __init__(self, port: str, bridge: ConnectionBridge, bluetooth: bool = False):
        super().__init__(name=f"rqft-conn-{port}", daemon=True)
        self.port = port
        self._bridge = bridge
        # A Bluetooth port is never re-opened on a timer: opening one whose
        # unit is off pages it for five seconds and the radio pages one
        # unit at a time, so the discovery lane does the paging for every
        # Bluetooth port and enables the worker when the unit answers.
        # Meanwhile the worker sits in OPEN_BACKOFF with this flag set and
        # the port is not reported busy, so the lane may probe it.
        self.bluetooth = bluetooth
        self.awaiting_reachable = False
        # The last open failure, kept so a sync that needed the open can
        # say what went wrong rather than only that it did.
        self._last_open_error: Optional[Exception] = None
        # Why the last transport failure happened, as a utils.serial_errors
        # cause; read by the manager to word a lost connection.
        self.last_error_cause: Optional[str] = None
        self._queue: "queue.Queue[_Op]" = queue.Queue()
        self._stop_event = threading.Event()
        self._cancel = threading.Event()
        self.enabled = False
        self._transport: Optional[SteadySerialTransport] = None
        self._driver: Optional[BlockingSessionDriver] = None
        self._fs: Optional[LocalDirFs] = None
        self._established: Optional[Established] = None
        self._state = ConnectionState.DISABLED
        self._backoff_index = 0
        self._retry_at = 0.0
        self._hello_retry_at = 0.0
        self._pending_end: Optional[Ended] = None
        # When an open last failed. A Bluetooth open that fails has paged
        # the unit for seconds; a sync asked for right after does not page
        # it again, it gets the answer that page already gave.
        self._open_failed_at = 0.0

    # -- public API (GUI thread, non-blocking) -------------------------

    def enable(self):
        """Start (or resume) auto-connecting to the device."""
        self.enabled = True
        # Drop a stale cancel left behind by request_disconnect(); it
        # would otherwise abort every reconnect HELLO in _drive().
        self._cancel.clear()
        self._backoff_index = 0
        self._retry_at = 0.0
        self._hello_retry_at = 0.0
        self.awaiting_reachable = False

    def retry_now(self):
        """Drop every backoff and try the port again at once: the operator
        pressed the scan button, or discovery just found the unit."""
        self._backoff_index = 0
        self._retry_at = 0.0
        self._hello_retry_at = 0.0
        self.awaiting_reachable = False

    def request_sync(self, auto: bool):
        """Queue a sync; connects first when needed. Results arrive as
        syncFinished/syncFailed bridge signals. Every sync removes what it
        has verified from the device; how much of the card survives is the
        device's own folders-to-keep setting, which it enforces by
        refusing the deletes that would break it."""
        self._cancel.clear()
        self._queue.put(_Op("sync", auto=auto))

    def request_cancel(self):
        """Abort the in-flight operation with ABORT(E_USER)."""
        self._cancel.set()

    def request_disconnect(self):
        """Close the session and port; stays DISABLED until enable()."""
        self.enabled = False
        self._cancel.set()
        self._queue.put(_Op("disconnect"))

    def shutdown(self):
        """Stop the thread and let it close its transport.

        Closing pyserial from this caller thread while the worker is in
        read() can clear its file descriptor underneath os.read(). Signal
        cancellation first and preserve the worker's sole transport
        ownership during shutdown.
        """
        self._stop_event.set()
        self._cancel.set()
        if self.ident is None:
            # A never-started worker cannot be racing transport I/O.
            self._close_transport()
            return
        self.join(timeout=3.0)
        if self.is_alive():
            # The worker is a daemon. Do not violate transport ownership
            # to force shutdown; process exit will reclaim a wedged handle.
            log.warning(f"Connection worker for {self.port} did not stop in time")

    # -- worker thread -------------------------------------------------

    def run(self):
        while not self._stop_event.is_set():
            try:
                op = self._queue.get(timeout=0.05)
            except queue.Empty:
                op = None

            try:
                if op is not None:
                    self._execute(op)
                    # A cancel consumed (or missed) by this op must not
                    # leak into later HELLO attempts or ops.
                    self._cancel.clear()
                elif not self.enabled:
                    self._set_state(ConnectionState.DISABLED)
                elif self._transport is None:
                    self._set_state(ConnectionState.OPEN_BACKOFF)
                    if self.awaiting_reachable:
                        # The discovery lane pages Bluetooth ports; it
                        # re-enables this worker when the unit answers.
                        pass
                    elif time.monotonic() >= self._retry_at:
                        self._try_open()
                else:
                    self._idle_tick()
            except OSError as e:
                self._on_transport_error(e)
            except Exception:
                log.exception(f"Unexpected error in connection worker for {self.port}")
                self._on_transport_error(OSError("internal error"))
        self._close_transport()

    def _execute(self, op: _Op):
        if op.kind == "disconnect":
            self._do_disconnect()
            return
        if op.kind == "sync":
            self._op_sync(op.auto)

    # -- transport / session lifecycle ---------------------------------

    def _try_open(self):
        kwargs = {"exclusive": True} if os.name == "posix" else {}
        try:
            # write_timeout, or a port whose device has gone takes the
            # session's writes and never returns from one: pyserial waits
            # on a write forever unless it is given a deadline.
            # The port is configured here and never again: a unit takes a
            # configuration write as its cable being replugged (see
            # utils.serial_transport).
            self._transport = SteadySerialTransport(
                self.port,
                baudrate=115200,
                write_timeout=settings.RQFT_WRITE_TIMEOUT_S,
                **kwargs,
            )
        except Exception as e:
            log.debug(f"Could not open {self.port}: {e}")
            self._transport = None
            self._last_open_error = e
            self._open_failed_at = time.monotonic()
            if self.bluetooth:
                log.info(f"{self.port} not reachable; waiting for discovery")
                self.awaiting_reachable = True
                return
            backoffs = settings.RQFT_OPEN_BACKOFF_S
            delay = backoffs[min(self._backoff_index, len(backoffs) - 1)]
            self._backoff_index += 1
            self._retry_at = time.monotonic() + delay
            return
        self._backoff_index = 0
        self._hello_retry_at = 0.0
        self._driver = BlockingSessionDriver(
            self._transport,
            self._new_session(),
            read_size=_READ_SIZE,
            io_timeout_s=0.05,
        )
        self._set_state(ConnectionState.LISTENING)

    def _new_session(self) -> Session:
        # fs is bound per session so a changed root directory is picked
        # up on the next session.
        self._fs = LocalDirFs(store.root_directory)
        return Session(Role.CONTROLLER, fs=self._fs, window=settings.RQFT_WINDOW)

    def _close_transport(self):
        transport = self._transport
        self._transport = None
        self._driver = None
        self._established = None
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    def _on_transport_error(self, error: Exception):
        log.info(f"Transport error on {self.port}: {error}")
        was_open = self._transport is not None
        self.last_error_cause = classify_port_error(error, opened=was_open)
        self._close_transport()
        self._backoff_index = 0
        self._retry_at = time.monotonic() + settings.RQFT_OPEN_BACKOFF_S[0]
        if self.bluetooth:
            # The unit went off or out of range. Paging it from here
            # would burn the radio; the lane pages on its own cadence.
            self.awaiting_reachable = True
        if was_open:
            self._bridge.connectionLost.emit(self.port, "unplugged")
        self._set_state(
            ConnectionState.OPEN_BACKOFF if self.enabled else ConnectionState.DISABLED
        )

    def _do_disconnect(self):
        self.enabled = False
        if self._driver is not None and self._session.state in (
            SessionState.ACTIVE,
            SessionState.HELLO_SENT,
        ):
            try:
                self._driver.abort(AbortReason.CLOSE)
            except Exception:
                pass
            self._bridge.connectionLost.emit(self.port, "closed")
        self._close_transport()
        self._set_state(ConnectionState.DISABLED)

    @property
    def _session(self) -> Session:
        assert self._driver is not None
        return self._driver.session

    def _set_state(self, state: ConnectionState):
        if state is not self._state:
            self._state = state
            self._bridge.stateChanged.emit(self.port, state)

    # -- idle pumping (keepalive + doorbell) ---------------------------

    def _idle_tick(self):
        if self._session.state is SessionState.ENDED:
            # Fresh idle session so a device doorbell HELLO can be answered.
            self._driver.replace_session(self._new_session())
        turn = self._driver.pump(max_wait_s=0.05)
        for event in turn.events:
            self._note_event(event)
            if isinstance(event, Established):
                # Peer-initiated HELLO while we sat idle: the doorbell.
                # The device's NOTIFY follows with the sync it wants.
                log.info(f"Doorbell from {self.port}")
                self._set_state(ConnectionState.CONNECTED)
                self._bridge.established.emit(self.port, True)
        self._after_events()
        if self._established is not None:
            self._set_state(ConnectionState.CONNECTED)
            return
        self._set_state(ConnectionState.LISTENING)
        if time.monotonic() >= self._hello_retry_at:
            self._try_hello()

    def _try_hello(self):
        try:
            self._do_connect()
        except (_SessionEnded, _OpTimeout, _Cancelled) as e:
            log.debug(f"HELLO to {self.port} not answered: {e}")
            # An unanswered HELLO is not a lost connection; drop the end
            # record so the idle pump does not report it.
            self._pending_end = None
            self._hello_retry_at = (
                time.monotonic() + settings.RQFT_HELLO_RETRY_BUSY_S
            )
            self._set_state(ConnectionState.LISTENING)
            return
        self._bridge.established.emit(self.port, False)

    def _do_connect(self):
        """Run the HELLO handshake; raises on failure."""
        if self._established is not None:
            return
        self._set_state(ConnectionState.CONNECTING)
        if self._session.state is not SessionState.IDLE:
            self._driver.replace_session(self._new_session())
        self._session.start(self._driver.now_ms())
        self._drive(lambda event: event if isinstance(event, Established) else None)
        self._set_state(ConnectionState.CONNECTED)

    # -- event plumbing ------------------------------------------------

    def _note_event(self, event):
        if isinstance(event, Established):
            self._established = event
            log.info(
                f"RQFT session established on {self.port}: sid=0x{event.sid:02X} "
                f"v{event.version} payload={event.max_payload} window={event.window}"
            )
        elif isinstance(event, Ended):
            self._established = None
            self._pending_end = event
            log.info(
                f"RQFT session on {self.port} ended: {event.reason.name} "
                f"({'peer' if event.from_peer else 'local'})"
            )
        elif isinstance(event, NotifyReceived):
            # The device asked us to pull files. Surfaced here so both
            # event-drain paths (idle pump and in-op drive) forward it.
            log.info(f"Sync notify from {self.port} (flags=0x{event.flags:08x})")
            self._bridge.notify.emit(self.port, event.flags)
        elif isinstance(event, Passthrough):
            text = event.data.decode("utf-8", errors="replace").strip()
            if text:
                log.debug(f"Device console {self.port}: {text}")

    def _after_events(self):
        """Translate a session end noticed during idle pumping into a
        state transition and HELLO retry schedule."""
        end = self._pending_end
        if end is None:
            return
        self._pending_end = None
        now = time.monotonic()
        if end.reason is AbortReason.E_BUSY and end.from_peer:
            # Device started a measurement; sit listening so the
            # post-measurement doorbell hits the clean idle-answer path.
            self._hello_retry_at = now + settings.RQFT_HELLO_RETRY_BUSY_S
            self._bridge.connectionLost.emit(self.port, "busy")
        elif end.reason is AbortReason.E_USER and not end.from_peer:
            self._hello_retry_at = now + settings.RQFT_HELLO_RETRY_CANCELLED_S
            self._bridge.connectionLost.emit(self.port, "cancelled")
        elif end.reason is AbortReason.CLOSE:
            self._bridge.connectionLost.emit(self.port, "closed")
        else:
            self._hello_retry_at = now + settings.RQFT_HELLO_RETRY_DEAD_S
            self._bridge.connectionLost.emit(self.port, "dead")
        self._set_disconnected_state()

    def _set_disconnected_state(self):
        if not self.enabled:
            self._set_state(ConnectionState.DISABLED)
        elif self._transport is None:
            self._set_state(ConnectionState.OPEN_BACKOFF)
        else:
            self._set_state(ConnectionState.LISTENING)

    def _abort_timed_out_operation(self):
        """End a stalled operation and publish lost-session state."""
        try:
            for event in self._driver.abort(AbortReason.E_TIMEOUT):
                self._note_event(event)
        except Exception:
            pass
        if self._pending_end is not None:
            self._after_events()
            return
        self._established = None
        self._hello_retry_at = (
            time.monotonic() + settings.RQFT_HELLO_RETRY_DEAD_S
        )
        self._bridge.connectionLost.emit(self.port, "dead")
        self._set_disconnected_state()

    def _drive(self, accept, progress=False):
        """Pump the session until accept() yields, with an idle watchdog.

        Raises _Cancelled, _OpTimeout, _SessionEnded, or _OperationFailed.
        """
        last_activity = time.monotonic()
        last_emit = 0.0
        last_marker = None
        while True:
            if self._stop_event.is_set():
                raise _Cancelled("shutting down")
            if self._cancel.is_set():
                for event in self._driver.abort(AbortReason.E_USER):
                    self._note_event(event)
                self._pending_end = None
                self._hello_retry_at = (
                    time.monotonic() + settings.RQFT_HELLO_RETRY_CANCELLED_S
                )
                raise _Cancelled("cancelled by user")
            turn = self._driver.pump(max_wait_s=0.02)
            # Passthrough console text, echoed bytes, and link-level ACKs
            # do not prove that the requested operation is progressing.
            if any(not isinstance(event, Passthrough) for event in turn.events):
                last_activity = time.monotonic()
            found = None
            failure = None
            for event in turn.events:
                self._note_event(event)
                if failure is not None or found is not None:
                    continue
                if isinstance(event, Ended):
                    failure = _SessionEnded(event)
                elif isinstance(event, OpFailed):
                    failure = _OperationFailed(event)
                else:
                    found = accept(event)
            if failure is not None:
                if not isinstance(failure, _SessionEnded):
                    self._pending_end = None
                # A _SessionEnded keeps _pending_end set so the caller's
                # _after_events() schedules the HELLO retry and reports
                # the lost connection.
                raise failure
            if found is not None:
                return found
            if progress:
                snapshot = self._session.progress()
                if snapshot is not None:
                    marker = (snapshot.phase, snapshot.done)
                    if marker != last_marker:
                        last_marker = marker
                        last_activity = time.monotonic()
                    now = time.monotonic()
                    if now - last_emit >= _PROGRESS_EMIT_INTERVAL_S:
                        last_emit = now
                        self._bridge.fileByteProgress.emit(
                            snapshot.done, snapshot.total or 0
                        )
            if time.monotonic() - last_activity > _OP_IDLE_TIMEOUT_S:
                raise _OpTimeout(f"no progress for {_OP_IDLE_TIMEOUT_S:.0f}s")

    # -- sync operation ------------------------------------------------

    def _recent_open_failure(self) -> Optional[Exception]:
        """The failure of an open that just happened, if paging again now
        would only repeat it."""
        if not self.bluetooth or self._last_open_error is None:
            return None
        if time.monotonic() - self._open_failed_at > settings.RQFT_BLUETOOTH_REOPEN_HOLD_S:
            return None
        return self._last_open_error

    def _op_sync(self, auto: bool):
        fetched: list[str] = []
        try:
            if self._transport is None:
                if self._recent_open_failure() is None:
                    self._try_open()
                if self._transport is None:
                    # The original failure, so the sync can say whether
                    # the port is held, gone, or a unit that is off.
                    cause = self._last_open_error
                    if isinstance(cause, OSError):
                        raise cause
                    raise OSError(str(cause) if cause else "serial port could not be opened")
            newly_connected = self._established is None
            self._do_connect()
            if newly_connected:
                self._bridge.established.emit(self.port, False)
            self._sync(fetched)
        except _Cancelled:
            log.info(f"Sync on {self.port} cancelled by user")
            self._bridge.syncFailed.emit(
                self.port, SyncError("cancelled", fetched=fetched)
            )
        except _SessionEnded as e:
            kind = (
                "busy"
                if e.event.reason is AbortReason.E_BUSY and e.event.from_peer
                else "ended"
            )
            self._after_events()
            self._bridge.syncFailed.emit(
                self.port,
                SyncError(kind, message=e.event.reason.name, fetched=fetched),
            )
        except _OperationFailed as e:
            self._bridge.syncFailed.emit(
                self.port,
                SyncError(
                    "op",
                    message=str(e),
                    err_code=e.event.code,
                    path=e.event.path,
                    fetched=fetched,
                ),
            )
        except _OpTimeout as e:
            # Free the wedged session; the idle pump reconnects later.
            self._abort_timed_out_operation()
            self._bridge.syncFailed.emit(
                self.port, SyncError("timeout", message=str(e), fetched=fetched)
            )
        except OSError as e:
            if self._cancel.is_set():
                # The operator gave up while the open was still paging the
                # unit. What they get is the cancel they asked for, not a
                # report on a port they had already stopped waiting on.
                log.info(f"Sync on {self.port} cancelled during open: {e}")
                self._bridge.syncFailed.emit(
                    self.port, SyncError("cancelled", fetched=fetched)
                )
            else:
                self._bridge.syncFailed.emit(
                    self.port,
                    SyncError(
                        "transport",
                        message=str(e),
                        fetched=fetched,
                        opened=self._transport is not None,
                    ),
                )
            self._on_transport_error(e)

    def _sync(self, fetched: list):
        """Fetch planned .prof files, reporting each committed path.

        Everything this sync leaves CRC-verified in the mirror is then
        removed from the device, folders the operator named but never
        measured into included. What survives is the device's own
        folders-to-keep setting: it refuses those deletes, and a refusal
        is not a failure.
        """
        missing, total_bytes, mirrored, list_complete, empty = self._build_sync_plan()
        skipped = len(mirrored)
        self._session.send_plan(len(missing), total_bytes, self._driver.now_ms())
        self._driver.flush()
        self._bridge.syncStarted.emit(self.port, len(missing), total_bytes)
        log.info(
            f"Sync {self.port}: {len(missing)} to fetch ({total_bytes} bytes), "
            f"{skipped} up to date"
        )

        # Without ALLOW_DELETE every DEL comes back E_DENIED, so there is no
        # point asking; the device simply keeps its copies.
        delete_remote = self._peer_allows_delete()
        if not delete_remote:
            log.warning(
                f"Sync {self.port}: device does not allow deletes, keeping its files"
            )
        # A file already in the mirror was left on the device by an earlier
        # sync that could not delete it, so it is deletable too.
        verified = [entry.path for entry in mirrored]
        # Done before the fetch: an empty folder is one mkdir, and a sync that
        # dies halfway has still carried the one thing that folder was.
        mirrored_empty = self._mirror_empty_folders(empty)

        failed_files = 0
        for index, entry in enumerate(missing):
            self._bridge.receivingFile.emit(entry.path, len(missing) - index)
            self._session.request_get(entry.path, now_ms=self._driver.now_ms())
            try:
                done = self._drive(
                    lambda event: event
                    if isinstance(event, GetDone) and event.path == entry.path
                    else None,
                    progress=True,
                )
            except _OperationFailed as e:
                # E.g. file removed on the device between LIST and GET;
                # the session survives, so continue with the next file.
                log.warning(f"Sync {self.port}: {e}")
                failed_files += 1
                if self._established is None:
                    # The session died in the same pump turn; do not
                    # request further GETs on it.
                    end = self._pending_end
                    if end is not None:
                        raise _SessionEnded(end) from e
                    raise _OpTimeout("session lost during sync") from e
                continue
            self._bridge.fileByteProgress.emit(done.size, done.size)
            self._apply_mtime(entry)
            fetched.append(entry.path)
            verified.append(entry.path)

        if failed_files:
            log.warning(f"Sync {self.port}: {failed_files} files failed to fetch")
        # Deleting last keeps the GET stream uninterrupted, and an
        # interrupted sync leaves the device untouched.
        deleted = 0
        if delete_remote:
            fetched_paths = set(fetched)
            unverified = [
                entry.path for entry in missing if entry.path not in fetched_paths
            ]
            folders, files = plan_device_deletes(
                verified,
                unverified,
                list_complete=list_complete,
                empty_folders=mirrored_empty,
            )
            deleted = self._delete_from_device(folders, files)
        self._bridge.syncFinished.emit(self.port, list(fetched), skipped, deleted)

    def _peer_allows_delete(self) -> bool:
        """Whether the device advertised the ALLOW_DELETE capability.
        Without it every DEL comes back E_DENIED (SPEC.md section 5.4)."""
        established = self._established
        return (
            established is not None
            and bool(established.peer_caps & CAP_ALLOW_DELETE)
        )

    def _delete_from_device(self, folders: list, files: list) -> int:
        """Remove verified content from the device, whole folders first.

        A refused delete does not fail the sync: rollview holds a verified
        copy either way, and a refusal is the expected answer for the
        folders the device is keeping. A delete that takes the session
        down does stop the batch.
        """
        if self._established is None:
            # The session went away with the batch; the device keeps its
            # copies and the next sync retries.
            return 0
        deleted = 0
        kept = 0
        failed = 0
        for path, is_dir in [(f, True) for f in folders] + [(f, False) for f in files]:
            self._session.request_del(path, is_dir=is_dir, now_ms=self._driver.now_ms())
            try:
                self._drive(
                    lambda event: event
                    if isinstance(event, DelDone)
                    and event.path == path
                    and event.is_dir == is_dir
                    else None
                )
            except _OperationFailed as e:
                if e.event.code == ErrCode.E_DENIED:
                    # The device is keeping this one; not a problem.
                    kept += 1
                else:
                    log.warning(f"Sync {self.port}: could not remove {path}: {e}")
                    failed += 1
                if self._established is None:
                    end = self._pending_end
                    if end is not None:
                        raise _SessionEnded(end) from e
                    raise _OpTimeout("session lost while deleting") from e
                continue
            deleted += 1
        if deleted:
            log.info(f"Sync {self.port}: removed {deleted} synced entries from the device")
        if kept:
            log.info(f"Sync {self.port}: device kept {kept} entries it was told to keep")
        if failed:
            log.warning(
                f"Sync {self.port}: {failed} entries could not be removed from the device"
            )
        return deleted

    def _build_sync_plan(self):
        """List remote profiles and plan the fetch batch.

        Returns (missing entries, total bytes, already-mirrored entries,
        listing complete, empty folders). A file whose local copy already
        matches by size and CRC counts as mirrored and is not fetched again;
        everything else is missing. An incomplete listing means the device
        could not read some of its own entries, which is what stops a later
        delete taking a folder as a unit.

        A folder entry with no measurement under it is an empty folder: the
        operator named it on the device and nothing was measured into it yet,
        or nothing that survived. It has no files to fetch, so mirroring it
        is all there is to do.
        """
        assert self._fs is not None
        entries: list[EntryListed] = []
        folder_entries: list[EntryListed] = []
        skipped_entries = 0

        self._session.request_list("", want_crc=True, now_ms=self._driver.now_ms())

        def accept_list(event):
            nonlocal skipped_entries
            if isinstance(event, EntryListed):
                if event.etype == _ETYPE_FILE:
                    entries.append(event)
                else:
                    folder_entries.append(event)
                return None
            if isinstance(event, EntrySkipped):
                skipped_entries += 1
                return None
            return event if isinstance(event, ListDone) else None

        self._drive(accept_list)
        if skipped_entries:
            log.warning(
                f"Device {self.port} listing skipped {skipped_entries} unreadable entries"
            )
            self._bridge.listWarnings.emit(self.port, skipped_entries)

        candidates = [entry for entry in entries if is_syncable_prof(entry.path)]
        occupied = {entry.path.partition("/")[0] for entry in candidates}
        empty = [
            entry
            for entry in folder_entries
            if is_syncable_folder(entry.path) and entry.path not in occupied
        ]

        missing: list[EntryListed] = []
        mirrored: list[EntryListed] = []
        for entry in candidates:
            local = self._fs.file_info(entry.path)
            if (
                entry.crc32 is not None
                and local is not None
                and local.size == entry.size
                and local.crc32 == entry.crc32
            ):
                # The local copy matches: count it as synced content.
                mirrored.append(entry)
            else:
                missing.append(entry)

        missing.sort(key=lambda entry: entry.path)
        total_bytes = sum(entry.size for entry in missing)
        return missing, total_bytes, mirrored, skipped_entries == 0, empty

    def _mirror_empty_folders(self, entries: list) -> list:
        """Create the mirror folder for every device folder holding no
        measurement, and return the paths that are now mirrored.

        A folder that cannot be created locally is left out of what is
        returned, so the device keeps it and the next sync tries again.
        """
        mirrored = []
        for entry in entries:
            target = Path(self._fs.root).joinpath(*entry.path.split("/"))
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log.warning(f"Could not create folder {entry.path}: {e}")
                continue
            self._apply_mtime(entry, target)
            mirrored.append(entry.path)
        if mirrored:
            log.info(
                f"Sync {self.port}: mirrored {len(mirrored)} folders with no "
                f"measurements in them"
            )
        return mirrored

    def _apply_mtime(self, entry: EntryListed, target: Optional[Path] = None):
        """Preserve the device modification time on what was mirrored.
        Entries from devices that report no mtime keep their local time."""
        if entry.mtime <= 0:
            return
        # Device timestamps are local wall clock, not epoch. See time_sync.
        mtime = device_wall_clock_to_epoch(entry.mtime)
        if target is None:
            target = Path(self._fs.root).joinpath(*entry.path.split("/"))
        try:
            os.utime(target, (mtime, mtime))
        except OSError as e:
            log.warning(f"Could not set mtime for {entry.path}: {e}")


class DeviceConnectionManager(QObject):
    """GUI-thread owner of all device connections and their policy."""

    connectionStateChanged = Signal(str, object)   # port, ConnectionState
    connectionLost = Signal(str, str)              # port, reason
    listWarnings = Signal(str, int)                # port, skipped entries

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: dict[str, DeviceConnectionWorker] = {}
        self._bridges: dict[str, ConnectionBridge] = {}
        self._states: dict[str, ConnectionState] = {}
        self.identities: dict[str, DeviceIdentity] = {}
        self._manually_disconnected: set[str] = set()
        # Ports the scan classified as Bluetooth: their workers leave the
        # paging to the discovery lane.
        self._bluetooth_ports: set[str] = set()
        # A unit reachable over both links gets one connection. The port an
        # operator picked for a unit, and when each port last answered.
        self._link_forced: dict[str, str] = {}
        self._last_seen: dict[str, float] = {}
        self._transfer_manager = None

    def set_transfer_manager(self, transfer_manager):
        self._transfer_manager = transfer_manager

    # -- connection registry -------------------------------------------

    def on_scan_results(self, port_items):
        """Auto-connect RQFT-capable devices found by a scan."""
        for item in port_items:
            if not getattr(item, "device_responded", False):
                continue
            if getattr(item, "transport", None) == "bluetooth":
                self._bluetooth_ports.add(item.device)
            else:
                self._bluetooth_ports.discard(item.device)
            if not getattr(item, "supports_rqft", False):
                continue
            self.identities[item.device] = DeviceIdentity(
                device_name=item.description or "",
                serial_number=item.serial_number or "",
                firmware_version=getattr(item, "firmware_version", "") or "",
            )
            self._last_seen[item.device] = time.monotonic()
            self._apply_link_choice(item.device)

    # -- one connection per unit ---------------------------------------

    def _unit_serial(self, port: str) -> str:
        identity = self.identities.get(port)
        return identity.serial_number if identity is not None else ""

    def _unit_ports(self, serial: str) -> list:
        """Every port this unit has been seen on, in a stable order."""
        return sorted(
            port for port, identity in self.identities.items()
            if identity.serial_number == serial
        )

    def _link_is_live(self, port: str) -> bool:
        """Whether this port still counts as one of its unit's links."""
        if self._states.get(port) is ConnectionState.CONNECTED:
            return True
        last_seen = self._last_seen.get(port)
        if last_seen is None:
            return False
        return (time.monotonic() - last_seen) <= settings.RQFT_LINK_CHOICE_STALE_S

    def _choose_link(self, serial: str) -> Optional[str]:
        """Which of a unit's ports carries its connection.

        The port an operator connected by hand wins for as long as it is
        there. Otherwise a session already up keeps it, since moving a live
        connection costs a sync and buys nothing. Failing both, Bluetooth,
        which is the better behaved of the two links today, and failing
        that whichever port answered most recently. A port quiet for
        RQFT_LINK_CHOICE_STALE_S drops out of the running, so pulling the
        USB cable hands the unit back to Bluetooth on its own.
        """
        ports = [
            port for port in self._unit_ports(serial)
            if port not in self._manually_disconnected
        ]
        if not ports:
            return None
        live = [port for port in ports if self._link_is_live(port)] or ports
        forced = self._link_forced.get(serial)
        if forced is not None:
            if forced in live:
                return forced
            # The link they picked has gone: the unit falls back to the
            # ordinary choice rather than waiting for a port that is not
            # there, and stops being pinned to it.
            self._link_forced.pop(serial, None)
        connected = [
            port for port in live
            if self._states.get(port) is ConnectionState.CONNECTED
        ]
        if connected:
            return connected[0]
        bluetooth = [port for port in live if port in self._bluetooth_ports]
        if settings.RQFT_PREFER_BLUETOOTH_LINK and bluetooth:
            return bluetooth[0]
        return max(live, key=lambda port: self._last_seen.get(port, 0.0))

    def _apply_link_choice(self, port: str, force: bool = False):
        """Hold one connection to the unit behind ``port``.

        The device binds its RQFT session to the link that established it
        and stops reading the other one, so a second connection to the
        same unit is talking to nobody: its HELLOs go unanswered, and the
        probe that follows reports a live unit as silent. One link at a
        time is what keeps the list telling the truth.
        """
        serial = self._unit_serial(port)
        if not serial:
            # A unit that reports no serial number cannot be paired with
            # anything, so every port it appears on stands on its own.
            if port not in self._manually_disconnected:
                self._ensure_worker(port)
            return
        if force:
            self._link_forced[serial] = port
        chosen = self._choose_link(serial)
        for other in self._unit_ports(serial):
            if other != chosen:
                self._release_link(other)
        if chosen is not None and chosen not in self._manually_disconnected:
            self._ensure_worker(chosen)

    def _release_link(self, port: str):
        """Let go of a port whose unit is connected on its other link."""
        worker = self._workers.get(port)
        if worker is None or not worker.enabled:
            return
        log.info(f"One connection per unit: releasing {port}")
        worker.request_disconnect()

    def _ensure_worker(self, port: str) -> DeviceConnectionWorker:
        worker = self._workers.get(port)
        if worker is not None and worker.is_alive():
            worker.enable()
            return worker
        bridge = ConnectionBridge(self)
        bridge.stateChanged.connect(self._on_state_changed)
        bridge.notify.connect(self._on_notify)
        bridge.connectionLost.connect(self._on_connection_lost)
        bridge.listWarnings.connect(self.listWarnings)
        worker = DeviceConnectionWorker(
            port, bridge, bluetooth=port in self._bluetooth_ports
        )
        self._workers[port] = worker
        self._bridges[port] = bridge
        worker.enable()
        worker.start()
        log.info(f"Started RQFT connection worker for {port}")
        return worker

    def manual_connect(self, port: str):
        self._manually_disconnected.discard(port)
        # An explicit connect moves the unit's link to this port, and lets
        # go of the other one: the operator asked for this one.
        self._last_seen[port] = time.monotonic()
        self._apply_link_choice(port, force=True)

    def allow_auto_connect(self, port: str):
        """Forget a manual disconnect, so the next scan result for the
        port connects it again. For the Connect action on a unit that has
        not answered yet: the connect happens when it does."""
        self._manually_disconnected.discard(port)

    def retry_all_now(self):
        """The scan button: every worker sitting in a backoff tries again.

        Bluetooth workers waiting on discovery are left waiting: the scan
        the button starts probes their ports, and a worker paging the same
        port at the same time would only fight it for the radio.
        """
        for worker in list(self._workers.values()):
            if not worker.is_alive() or not worker.enabled:
                continue
            if worker.bluetooth and worker.awaiting_reachable:
                continue
            worker.retry_now()

    def port_appeared(self, port: str):
        """The port is in the list again. A worker waiting out a backoff
        on it -- its cable was pulled, and every open since has failed --
        tries at once rather than in up to thirty seconds. Bluetooth
        workers are left to discovery, as in retry_all_now."""
        worker = self._workers.get(port)
        if worker is None or not worker.is_alive() or not worker.enabled:
            return
        if worker.bluetooth:
            return
        worker.retry_now()

    def manual_disconnect(self, port: str):
        self._manually_disconnected.add(port)
        worker = self._workers.get(port)
        if worker is not None:
            worker.request_disconnect()
        # The unit may still be reachable on its other link, which is now
        # free to take it: disconnecting one port is not disowning the unit.
        self._apply_link_choice(port)

    def get_connection(self, port: str) -> Optional[DeviceConnectionWorker]:
        """Return a usable (enabled, running) worker for the port."""
        worker = self._workers.get(port)
        if worker is not None and worker.is_alive() and worker.enabled:
            return worker
        return None

    def bridge_for(self, port: str) -> Optional[ConnectionBridge]:
        return self._bridges.get(port)

    def last_error_cause(self, port: str) -> Optional[str]:
        """Why the worker on this port last failed, for a sync that cannot
        start: a utils.serial_errors cause, or None when it never failed."""
        worker = self._workers.get(port)
        return getattr(worker, "last_error_cause", None) if worker else None

    def connection_state(self, port: str) -> Optional[ConnectionState]:
        if port in self._workers:
            return self._states.get(port, ConnectionState.DISABLED)
        if port in self._manually_disconnected:
            return ConnectionState.DISABLED
        return None

    def busy_ports(self) -> dict:
        """Ports whose serial device is (or may soon be) held by a
        connection worker; the scanner must not probe these. Cached
        identity counts as a scan response only while its RQFT session
        is currently connected."""
        busy = {}
        # Copied first: the discovery lane calls this from its own thread
        # while this thread may be adding a worker.
        for port, worker in list(self._workers.items()):
            if worker.is_alive() and worker.enabled and not worker.awaiting_reachable:
                busy[port] = BusyPortStatus(
                    identity=self.identities.get(
                        port, DeviceIdentity("", "", "")
                    ),
                    connected=(
                        self._states.get(port) is ConnectionState.CONNECTED
                    ),
                )
        # The other link of a unit whose session is live: the device is not
        # reading that port at all while its session is bound elsewhere, so
        # a probe there would report a working unit as silent. It is known
        # and it is reachable -- just not on this port.
        identities = list(self.identities.items())
        connected_units = {
            identity.serial_number for port, identity in identities
            if identity.serial_number
            and self._states.get(port) is ConnectionState.CONNECTED
        }
        for port, identity in identities:
            if port in busy:
                continue
            if identity.serial_number in connected_units:
                busy[port] = BusyPortStatus(identity=identity, connected=True)
        return busy

    def device_label(self, port: str) -> str:
        identity = self.identities.get(port)
        if identity is None:
            return port
        label = identity.device_name or port
        if identity.serial_number:
            label += f" ({identity.serial_number})"
        return label

    def describe_lost_connection(self, port: str) -> str:
        """Words for a connection the worker on ``port`` lost: which way
        the port failed, and what to do about it."""
        worker = self._workers.get(port)
        cause = getattr(worker, "last_error_cause", None) or CAUSE_LINK_LOST
        label = self.device_label(port)
        return describe_port_error(cause, port, "" if label == port else label).body

    # -- bridge slots (GUI thread) -------------------------------------

    def _on_state_changed(self, port: str, state):
        self._states[port] = state
        self.connectionStateChanged.emit(port, state)

    def _on_notify(self, port: str, flags: int):
        if self._transfer_manager is None:
            return
        # The device asked us to pull. Its sync-mode flags are logged but
        # not acted on: there is one sync behaviour now, and it deletes what
        # it has verified either way. The flags stay on the wire so a future
        # distinction has somewhere to live.
        log.info(
            f"Device {port} sync flags: "
            f"incremental={bool(flags & NOTIFY_SYNC_INCREMENTAL)} "
            f"delete_after_sync={bool(flags & NOTIFY_DELETE_AFTER_SYNC)}"
        )
        self._transfer_manager.request_auto_sync(port)

    def _on_connection_lost(self, port: str, reason: str):
        # Said in full here rather than in the status row: a device that
        # has gone shows in the device list, and the reason it gave
        # belongs where someone diagnosing it will look for it.
        log.info(f"Connection lost on {port} ({reason}): {self.describe_lost_connection(port)}")
        self.connectionLost.emit(port, reason)

    # -- shutdown ------------------------------------------------------

    def shutdown_all(self):
        """Stop every worker; signal all first so joins overlap."""
        for worker in self._workers.values():
            worker._stop_event.set()
            worker._cancel.set()
        for worker in self._workers.values():
            worker.shutdown()
        self._workers.clear()
