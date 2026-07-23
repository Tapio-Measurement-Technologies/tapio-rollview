"""
Persistent RQFT device connections.

Each RQFT-capable device gets a DeviceConnectionWorker: a plain daemon
thread that is the sole owner of the serial transport and the sans-io
Session (driven by BlockingSessionDriver). Between operations the worker
pumps the session so keepalive PINGs flow and a device-initiated doorbell
HELLO is answered. All GUI communication crosses through ConnectionBridge
Qt signals (queued cross-thread delivery).

DeviceConnectionManager lives in the GUI thread and owns the workers,
the auto-connect policy, the sync-on-connect prompt policy, and the
periodic sync timer.
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

from PySide6.QtCore import QObject, QTimer, Signal

import settings
import store
from rqft.client import BlockingSessionDriver, LocalDirFs
from rqft.events import (
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
from rqft.messages import NOTIFY_SYNC_INCREMENTAL, ErrCode, Role
from rqft.serial_transport import SerialTransport
from rqft.session import Session, SessionState
from utils import preferences
from utils.rqft_support import DeviceIdentity, is_syncable_prof
from utils.sync_history import SyncHistory
from utils.translation import _

log = logging.getLogger(__name__)

# Transport read chunk used by the worker loop.
_READ_SIZE = 65536

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


def describe_sync_error(error: SyncError) -> str:
    """Build a translated user-facing message for a failed sync."""
    if error.kind == "busy":
        return _("DEVICE_BUSY_STATUS")
    if error.kind == "transport":
        return f"{_('SYNC_ERROR_TRANSPORT')} {error.message}".strip()
    if error.kind == "timeout":
        return _("SYNC_ERROR_TIMEOUT")
    if error.kind == "ended":
        return f"{_('SYNC_ERROR_ENDED')} {error.message}".strip()
    if error.kind == "op":
        hint = _(ERR_MESSAGE_KEYS[error.err_code]) if error.err_code in ERR_MESSAGE_KEYS else ""
        where = f" '{error.path}'" if error.path else ""
        return f"{_('SYNC_ERROR_OPERATION')}{where}: {hint or error.message}"
    return error.message


class ConnectionBridge(QObject):
    """The single Qt crossing point for one worker thread.

    Created in the GUI thread; the worker only calls signal.emit(), which
    Qt delivers as queued cross-thread calls.
    """
    stateChanged = Signal(str, object)          # port, ConnectionState
    established = Signal(str, bool)             # port, by_doorbell
    notify = Signal(str, int)                   # port, NOTIFY flags
    connectionLost = Signal(str, str)           # port, busy|dead|unplugged|closed|cancelled
    syncCheckFinished = Signal(str, int, int)    # port, missing files, missing bytes
    syncStarted = Signal(str, int, int)         # port, nfiles, nbytes
    receivingFile = Signal(str, int)            # path, files_left (countdown)
    fileByteProgress = Signal(int, int)         # current file: done, total
    syncFinished = Signal(str, list, int)       # port, fetched paths, skipped count
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
    incremental: bool = False


class DeviceConnectionWorker(threading.Thread):
    """Owns the serial transport and Session for one device; sole thread
    touching either. Non-blocking public API for the GUI thread."""

    def __init__(self, port: str, bridge: ConnectionBridge, device_key: str = ""):
        super().__init__(name=f"rqft-conn-{port}", daemon=True)
        self.port = port
        self._bridge = bridge
        # Serial number when known, else the port; names the sync history.
        self._device_key = device_key or port
        self._queue: "queue.Queue[_Op]" = queue.Queue()
        self._stop_event = threading.Event()
        self._cancel = threading.Event()
        self.enabled = False
        self._transport: Optional[SerialTransport] = None
        self._driver: Optional[BlockingSessionDriver] = None
        self._fs: Optional[LocalDirFs] = None
        self._established: Optional[Established] = None
        self._state = ConnectionState.DISABLED
        self._backoff_index = 0
        self._retry_at = 0.0
        self._hello_retry_at = 0.0
        self._pending_end: Optional[Ended] = None

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

    def request_sync(self, auto: bool, incremental: bool = False):
        """Queue a sync; connects first when needed. Results arrive as
        syncFinished/syncFailed bridge signals. An incremental sync skips
        remote files recorded in the device's sync history even when the
        local copy was deleted."""
        self._cancel.clear()
        self._queue.put(_Op("sync", auto=auto, incremental=incremental))

    def request_sync_check(self):
        """Queue a read-only list/diff used before offering a sync."""
        self._cancel.clear()
        self._queue.put(_Op("check"))

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
                    if time.monotonic() >= self._retry_at:
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
        if op.kind == "check":
            self._op_sync_check()
            return
        if op.kind == "sync":
            self._op_sync(op.auto, op.incremental)

    # -- transport / session lifecycle ---------------------------------

    def _try_open(self):
        kwargs = {"exclusive": True} if os.name == "posix" else {}
        try:
            self._transport = SerialTransport(self.port, baudrate=115200, **kwargs)
        except Exception as e:
            log.debug(f"Could not open {self.port}: {e}")
            self._transport = None
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
        self._close_transport()
        self._backoff_index = 0
        self._retry_at = time.monotonic() + settings.RQFT_OPEN_BACKOFF_S[0]
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
            if turn.events or turn.bytes_received:
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

    def _op_sync_check(self):
        """Report missing files without fetching them."""
        try:
            if self._transport is None:
                self._try_open()
                if self._transport is None:
                    raise OSError("serial port could not be opened")
            newly_connected = self._established is None
            self._do_connect()
            if newly_connected:
                self._bridge.established.emit(self.port, False)
            missing, total_bytes, _, _ = self._build_sync_plan()
            self._bridge.syncCheckFinished.emit(
                self.port, len(missing), total_bytes
            )
        except _Cancelled:
            log.info(f"Sync check on {self.port} cancelled")
        except _SessionEnded as e:
            self._after_events()
            log.info(f"Sync check on {self.port} ended: {e.event.reason.name}")
        except _OperationFailed as e:
            log.warning(f"Sync check on {self.port} failed: {e}")
        except _OpTimeout:
            try:
                for event in self._driver.abort(AbortReason.E_TIMEOUT):
                    self._note_event(event)
            except Exception:
                pass
            self._pending_end = None
            self._hello_retry_at = (
                time.monotonic() + settings.RQFT_HELLO_RETRY_DEAD_S
            )
            log.warning(f"Sync check on {self.port} timed out")
        except OSError as e:
            log.warning(f"Sync check on {self.port} failed: {e}")
            self._on_transport_error(e)

    def _op_sync(self, auto: bool, incremental: bool = False):
        fetched: list[str] = []
        try:
            if self._transport is None:
                self._try_open()
                if self._transport is None:
                    raise OSError("serial port could not be opened")
            newly_connected = self._established is None
            self._do_connect()
            if newly_connected:
                self._bridge.established.emit(self.port, False)
            self._sync(fetched, incremental)
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
            try:
                for event in self._driver.abort(AbortReason.E_TIMEOUT):
                    self._note_event(event)
            except Exception:
                pass
            self._pending_end = None
            self._hello_retry_at = time.monotonic() + settings.RQFT_HELLO_RETRY_DEAD_S
            self._bridge.syncFailed.emit(
                self.port, SyncError("timeout", message=str(e), fetched=fetched)
            )
        except OSError as e:
            self._bridge.syncFailed.emit(
                self.port, SyncError("transport", message=str(e), fetched=fetched)
            )
            self._on_transport_error(e)

    def _sync(self, fetched: list, incremental: bool = False):
        """Fetch planned .prof files, reporting each committed path.

        An incremental sync (device NOTIFY with the SYNC_INCREMENTAL
        sync-mode flag) additionally drops remote files recorded in the
        device's sync history, so files deleted from the local mirror
        stay gone.
        """
        missing, total_bytes, skipped, history = self._build_sync_plan(incremental)
        self._session.send_plan(len(missing), total_bytes, self._driver.now_ms())
        self._driver.flush()
        self._bridge.syncStarted.emit(self.port, len(missing), total_bytes)
        log.info(
            f"Sync {self.port}: {len(missing)} to fetch ({total_bytes} bytes), "
            f"{skipped} up to date"
        )

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
            # Persist per file so a file pulled once is never re-pulled
            # by a later incremental sync even if this batch fails.
            history.record(entry.path, entry.size, entry.crc32)
            history.save()

        if failed_files:
            log.warning(f"Sync {self.port}: {failed_files} files failed to fetch")
        self._bridge.syncFinished.emit(self.port, list(fetched), skipped)

    def _build_sync_plan(self, incremental: bool = False):
        """List remote profiles and plan the fetch batch.

        Returns (missing entries, total bytes, skipped count, history).
        Incremental mode first drops candidates the sync history knows,
        then both modes skip files whose local copy already matches by
        size and CRC. The history is rebuilt from matches and pruned to
        the current device listing, so a full sync repairs it.
        """
        assert self._fs is not None
        entries: list[EntryListed] = []
        skipped_entries = 0

        self._session.request_list("", want_crc=True, now_ms=self._driver.now_ms())

        def accept_list(event):
            nonlocal skipped_entries
            if isinstance(event, EntryListed):
                if event.etype == 0:
                    entries.append(event)
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
        history = SyncHistory(self._device_key, self._fs.root)
        history.load()

        suppressed = 0
        if incremental:
            remaining = []
            for entry in candidates:
                if history.known(entry.path, entry.crc32):
                    # Already synced once; a missing local copy means the
                    # user deleted it, so do not resurrect it.
                    suppressed += 1
                else:
                    remaining.append(entry)
        else:
            remaining = candidates

        missing: list[EntryListed] = []
        skipped = 0
        for entry in remaining:
            local = self._fs.file_info(entry.path)
            if (
                entry.crc32 is not None
                and local is not None
                and local.size == entry.size
                and local.crc32 == entry.crc32
            ):
                skipped += 1
                # The local copy matches: count it as synced content.
                history.record(entry.path, entry.size, entry.crc32)
            else:
                missing.append(entry)

        history.prune(entry.path for entry in candidates)
        history.save()
        if suppressed:
            log.info(
                f"Sync {self.port}: {suppressed} previously synced files "
                f"suppressed by incremental history"
            )

        missing.sort(key=lambda entry: entry.path)
        total_bytes = sum(entry.size for entry in missing)
        return missing, total_bytes, skipped, history

    def _apply_mtime(self, entry: EntryListed):
        """Preserve the device modification time on the downloaded file.
        Files from devices that report no mtime keep their download time."""
        if entry.mtime <= 0:
            return
        target = Path(self._fs.root).joinpath(*entry.path.split("/"))
        try:
            os.utime(target, (entry.mtime, entry.mtime))
        except OSError as e:
            log.warning(f"Could not set mtime for {entry.path}: {e}")


class DeviceConnectionManager(QObject):
    """GUI-thread owner of all device connections and their policy."""

    connectionStateChanged = Signal(str, object)   # port, ConnectionState
    connectionLost = Signal(str, str)              # port, reason
    listWarnings = Signal(str, int)                # port, skipped entries
    syncPromptRequested = Signal(str, str)         # port, device label
    syncPromptDismissRequested = Signal(str)       # port

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: dict[str, DeviceConnectionWorker] = {}
        self._bridges: dict[str, ConnectionBridge] = {}
        self._states: dict[str, ConnectionState] = {}
        self.identities: dict[str, DeviceIdentity] = {}
        self._manually_disconnected: set[str] = set()
        self._prompted_serials: set[str] = set()
        self._transfer_manager = None
        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._on_periodic_timeout)
        self.apply_settings()

    def set_transfer_manager(self, transfer_manager):
        self._transfer_manager = transfer_manager

    # -- connection registry -------------------------------------------

    def on_scan_results(self, port_items):
        """Auto-connect RQFT-capable devices found by a scan."""
        for item in port_items:
            if not getattr(item, "device_responded", False):
                continue
            if not getattr(item, "supports_rqft", False):
                continue
            self.identities[item.device] = DeviceIdentity(
                device_name=item.description or "",
                serial_number=item.serial_number or "",
                firmware_version=getattr(item, "firmware_version", "") or "",
            )
            if item.device in self._manually_disconnected:
                continue
            self._ensure_worker(item.device)

    def _ensure_worker(self, port: str) -> DeviceConnectionWorker:
        worker = self._workers.get(port)
        if worker is not None and worker.is_alive():
            worker.enable()
            return worker
        bridge = ConnectionBridge(self)
        bridge.stateChanged.connect(self._on_state_changed)
        bridge.established.connect(self._on_established)
        bridge.notify.connect(self._on_notify)
        bridge.connectionLost.connect(self._on_connection_lost)
        bridge.syncCheckFinished.connect(self._on_sync_check_finished)
        bridge.listWarnings.connect(self.listWarnings)
        identity = self.identities.get(port)
        device_key = identity.serial_number if identity and identity.serial_number else port
        worker = DeviceConnectionWorker(port, bridge, device_key=device_key)
        self._workers[port] = worker
        self._bridges[port] = bridge
        worker.enable()
        worker.start()
        log.info(f"Started RQFT connection worker for {port}")
        return worker

    def manual_connect(self, port: str):
        self._manually_disconnected.discard(port)
        self._ensure_worker(port)

    def manual_disconnect(self, port: str):
        self._manually_disconnected.add(port)
        worker = self._workers.get(port)
        if worker is not None:
            worker.request_disconnect()
        self.syncPromptDismissRequested.emit(port)

    def get_connection(self, port: str) -> Optional[DeviceConnectionWorker]:
        """Return a usable (enabled, running) worker for the port."""
        worker = self._workers.get(port)
        if worker is not None and worker.is_alive() and worker.enabled:
            return worker
        return None

    def bridge_for(self, port: str) -> Optional[ConnectionBridge]:
        return self._bridges.get(port)

    def connection_state(self, port: str) -> Optional[ConnectionState]:
        if port in self._workers:
            return self._states.get(port, ConnectionState.DISABLED)
        if port in self._manually_disconnected:
            return ConnectionState.DISABLED
        return None

    def busy_ports(self) -> dict:
        """Ports whose serial device is (or may soon be) held by a
        connection worker; the scanner must not probe these."""
        busy = {}
        for port, worker in self._workers.items():
            if worker.is_alive() and worker.enabled:
                busy[port] = self.identities.get(
                    port, DeviceIdentity("", "", "")
                )
        return busy

    def device_label(self, port: str) -> str:
        identity = self.identities.get(port)
        if identity is None:
            return port
        label = identity.device_name or port
        if identity.serial_number:
            label += f" ({identity.serial_number})"
        return label

    # -- bridge slots (GUI thread) -------------------------------------

    def _on_state_changed(self, port: str, state):
        self._states[port] = state
        self.connectionStateChanged.emit(port, state)

    def _on_established(self, port: str, by_doorbell: bool):
        if self._transfer_manager is None:
            return
        if by_doorbell:
            # The device rang to bring a session up; its NOTIFY follows
            # with the sync it wants, so nothing to do yet.
            return
        if self._transfer_manager.has_pending_sync(port):
            return
        identity = self.identities.get(port)
        key = identity.serial_number if identity and identity.serial_number else port
        if key in self._prompted_serials:
            return
        worker = self.get_connection(port)
        if worker is None:
            return
        self._prompted_serials.add(key)
        worker.request_sync_check()

    def _on_notify(self, port: str, flags: int):
        if self._transfer_manager is None:
            return
        # The device asked us to pull: sync without prompting. The
        # SYNC_INCREMENTAL sync-mode flag (post-measurement autosync)
        # asks for new files only; the device's manual sync button sends
        # flags 0 and gets a full sync. DELETE_AFTER_SYNC is not acted
        # on yet.
        self.syncPromptDismissRequested.emit(port)
        self._transfer_manager.request_auto_sync(
            port, incremental=bool(flags & NOTIFY_SYNC_INCREMENTAL)
        )

    def _on_sync_check_finished(self, port: str, nfiles: int, nbytes: int):
        if nfiles <= 0:
            log.info(f"Sync check {port}: no files to fetch")
            return
        if self._transfer_manager is None:
            return
        if self._transfer_manager.has_pending_sync(port):
            return
        self.syncPromptRequested.emit(port, self.device_label(port))

    def _on_connection_lost(self, port: str, reason: str):
        if reason in ("unplugged", "closed"):
            self.syncPromptDismissRequested.emit(port)
        self.connectionLost.emit(port, reason)

    # -- periodic sync -------------------------------------------------

    def apply_settings(self):
        """(Re)start the periodic sync timer from current preferences."""
        if preferences.periodic_sync_enabled:
            interval_ms = preferences.periodic_sync_interval_minutes * 60 * 1000
            self._periodic_timer.start(interval_ms)
        else:
            self._periodic_timer.stop()

    def _on_periodic_timeout(self):
        if self._transfer_manager is None:
            return
        for port, state in self._states.items():
            if state is ConnectionState.CONNECTED:
                # Incremental so a periodic sync does not resurrect files
                # the user deleted from the mirror.
                self._transfer_manager.request_auto_sync(port, incremental=True)

    # -- shutdown ------------------------------------------------------

    def shutdown_all(self):
        """Stop every worker; signal all first so joins overlap."""
        for worker in self._workers.values():
            worker._stop_event.set()
            worker._cancel.set()
        for worker in self._workers.values():
            worker.shutdown()
        self._workers.clear()
