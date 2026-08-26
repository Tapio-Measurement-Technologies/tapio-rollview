import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication

import store
from rqft.client import BlockingSessionDriver, LocalDirFs, PumpResult
from rqft.demo import LoopbackResponder, SocketTransport
from rqft.events import Ended, Established, Passthrough
from rqft.link import AbortReason
from rqft.messages import NOTIFY_SYNC_INCREMENTAL, Role
from rqft.session import Session
from utils.rqft_support import DeviceIdentity
from workers.device_connection import (
    ConnectionBridge,
    ConnectionState,
    DeviceConnectionManager,
    DeviceConnectionWorker,
    _OpTimeout,
)
from workers.file_transfer import FileTransferManager


def wait_until(condition, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return condition()


class BridgeRecorder:
    """Collects every bridge signal emission for assertions."""

    def __init__(self, bridge: ConnectionBridge):
        self.states = []
        self.established = []
        self.notify_flags = []
        self.lost = []
        self.sync_checks = []
        self.sync_started = []
        self.sync_finished = []
        self.deleted_counts = []
        self.sync_failed = []
        bridge.stateChanged.connect(lambda port, state: self.states.append(state))
        bridge.established.connect(
            lambda port, by_doorbell: self.established.append(by_doorbell)
        )
        bridge.notify.connect(lambda port, flags: self.notify_flags.append(flags))
        bridge.connectionLost.connect(lambda port, reason: self.lost.append(reason))
        bridge.syncCheckFinished.connect(
            lambda port, nfiles, nbytes: self.sync_checks.append((nfiles, nbytes))
        )
        bridge.syncStarted.connect(
            lambda port, nfiles, nbytes: self.sync_started.append((nfiles, nbytes))
        )
        bridge.syncFinished.connect(self._on_sync_finished)
        bridge.syncFailed.connect(
            lambda port, error: self.sync_failed.append(error)
        )

    def _on_sync_finished(self, port, fetched, skipped, deleted):
        self.sync_finished.append((fetched, skipped))
        self.deleted_counts.append(deleted)


class DeviceConnectionTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.left_sock, self.right_sock = socket.socketpair()
        self.device_dir = tempfile.TemporaryDirectory(prefix="rqft-test-device-")
        self.local_dir = tempfile.TemporaryDirectory(prefix="rqft-test-local-")
        self.addCleanup(self.device_dir.cleanup)
        self.addCleanup(self.local_dir.cleanup)

        self._original_root = store.root_directory
        store.root_directory = self.local_dir.name
        self.addCleanup(self._restore_root)

        self._simulate_unplugged = False
        transport_patch = patch(
            "workers.device_connection.SerialTransport",
            side_effect=self._make_transport,
        )
        transport_patch.start()
        self.addCleanup(transport_patch.stop)

        self.bridge = ConnectionBridge()
        self.recorder = BridgeRecorder(self.bridge)
        self.worker = DeviceConnectionWorker("TESTPORT", self.bridge)
        self.addCleanup(self._shutdown_worker)

    def _make_transport(self, *args, **kwargs):
        if self._simulate_unplugged:
            raise OSError("port gone")
        return SocketTransport(self.left_sock)

    def _restore_root(self):
        store.root_directory = self._original_root

    def _shutdown_worker(self):
        self.worker.shutdown()
        for sock in (self.left_sock, self.right_sock):
            try:
                sock.close()
            except OSError:
                pass

    def seed_device_tree(self):
        root = Path(self.device_dir.name)
        (root / "roll").mkdir()
        (root / "roll" / "a.prof").write_bytes(b"profile-data-" * 100)
        (root / "roll" / "mean.prof").write_bytes(b"mean-data")
        (root / "roll" / "readme.txt").write_text("not a profile")


class TestWorkerShutdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_transport_is_closed_by_worker_after_read_finishes(self):
        class SlowReadTransport:
            def __init__(self):
                self.read_entered = threading.Event()
                self.reading = False
                self.closed = threading.Event()
                self.closed_while_reading = False
                self.closed_by = None

            def write(self, data):
                pass

            def read(self, max_len, timeout):
                self.reading = True
                self.read_entered.set()
                try:
                    self.closed.wait(0.2)
                    return b""
                finally:
                    self.reading = False

            def close(self):
                self.closed_while_reading = self.reading
                self.closed_by = threading.current_thread()
                self.closed.set()

        transport = SlowReadTransport()
        bridge = ConnectionBridge()
        worker = DeviceConnectionWorker("TESTPORT", bridge)
        self.addCleanup(worker.shutdown)

        with patch(
            "workers.device_connection.SerialTransport",
            return_value=transport,
        ):
            worker.enable()
            worker.start()
            self.assertTrue(transport.read_entered.wait(2.0))
            worker.shutdown()

        self.assertTrue(transport.closed.is_set())
        self.assertFalse(transport.closed_while_reading)
        self.assertIs(transport.closed_by, worker)

    def test_passthrough_noise_does_not_keep_operation_alive(self):
        class StepClock:
            def __init__(self):
                self.value = 0

            def __call__(self):
                self.value += 1
                return self.value

        class NoiseDriver:
            def __init__(self):
                self.session = MagicMock()
                self.pump_count = 0

            def pump(self, max_wait_s):
                self.pump_count += 1
                if self.pump_count > 10:
                    raise AssertionError("serial noise kept operation alive")
                return PumpResult((Passthrough(b"console noise"),), 13)

        worker = DeviceConnectionWorker("TESTPORT", ConnectionBridge())
        driver = NoiseDriver()
        worker._driver = driver

        with (
            patch(
                "workers.device_connection.time.monotonic",
                side_effect=StepClock(),
            ),
            patch("workers.device_connection._OP_IDLE_TIMEOUT_S", 3),
        ):
            with self.assertRaises(_OpTimeout):
                worker._drive(lambda _event: None)

        self.assertLessEqual(driver.pump_count, 4)

    def test_operation_timeout_publishes_disconnected_state(self):
        bridge = ConnectionBridge()
        recorder = BridgeRecorder(bridge)
        worker = DeviceConnectionWorker("TESTPORT", bridge)
        worker.enabled = True
        worker._transport = MagicMock()
        worker._driver = MagicMock()
        worker._driver.abort.return_value = (
            Ended(AbortReason.E_TIMEOUT, from_peer=False),
        )
        worker._state = ConnectionState.CONNECTED
        worker._established = MagicMock()

        worker._abort_timed_out_operation()

        self.assertEqual(recorder.lost, ["dead"])
        self.assertEqual(recorder.states, [ConnectionState.LISTENING])
        self.assertIsNone(worker._established)


class TestSyncFlow(DeviceConnectionTestBase):
    def setUp(self):
        super().setUp()
        self.seed_device_tree()
        self.responder = LoopbackResponder(self.right_sock, Path(self.device_dir.name))
        self.responder.start()

    def test_connects_and_syncs_only_prof_files(self):
        self.worker.enable()
        self.worker.start()

        self.assertTrue(
            wait_until(lambda: len(self.recorder.established) > 0),
            "worker did not establish a session",
        )
        self.assertFalse(self.recorder.established[0])  # self-initiated
        self.assertIn(ConnectionState.CONNECTED, self.recorder.states)

        self.worker.request_sync(auto=False)
        self.assertTrue(
            wait_until(lambda: len(self.recorder.sync_finished) > 0),
            f"sync did not finish (failures: {self.recorder.sync_failed})",
        )
        fetched, skipped = self.recorder.sync_finished[0]
        self.assertEqual(fetched, ["roll/a.prof"])
        self.assertEqual(skipped, 0)

        local = Path(self.local_dir.name) / "roll" / "a.prof"
        self.assertTrue(local.is_file())
        self.assertEqual(local.read_bytes(), b"profile-data-" * 100)
        self.assertFalse((Path(self.local_dir.name) / "roll" / "mean.prof").exists())
        self.assertFalse((Path(self.local_dir.name) / "roll" / "readme.txt").exists())

        # Second sync: everything is up to date, nothing is fetched and
        # the plan announces zero files (keeps auto-syncs invisible).
        self.worker.request_sync(auto=True)
        self.assertTrue(wait_until(lambda: len(self.recorder.sync_finished) > 1))
        fetched2, skipped2 = self.recorder.sync_finished[1]
        self.assertEqual(fetched2, [])
        self.assertEqual(skipped2, 1)
        self.assertEqual(self.recorder.sync_started[-1][0], 0)

    def test_incremental_sync_does_not_resurrect_deleted_local_file(self):
        self.worker.enable()
        self.worker.start()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))

        # Full sync records roll/a.prof in the device's sync history.
        self.worker.request_sync(auto=False)
        self.assertTrue(wait_until(lambda: len(self.recorder.sync_finished) > 0))
        local = Path(self.local_dir.name) / "roll" / "a.prof"
        self.assertTrue(local.is_file())

        # The user deletes the mirror copy; an incremental sync (the
        # post-measurement NOTIFY) must not bring it back.
        local.unlink()
        self.worker.request_sync(auto=True, incremental=True)
        self.assertTrue(wait_until(lambda: len(self.recorder.sync_finished) > 1))
        fetched, _ = self.recorder.sync_finished[1]
        self.assertEqual(fetched, [])
        self.assertFalse(local.exists())

        # A full sync (device sync button / manual PC sync) restores it.
        self.worker.request_sync(auto=False)
        self.assertTrue(wait_until(lambda: len(self.recorder.sync_finished) > 2))
        fetched, _ = self.recorder.sync_finished[2]
        self.assertEqual(fetched, ["roll/a.prof"])
        self.assertTrue(local.is_file())

    def test_sync_check_reports_missing_file_without_fetching_it(self):
        self.worker.enable()
        self.worker.start()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))

        self.worker.request_sync_check()

        self.assertTrue(wait_until(lambda: len(self.recorder.sync_checks) > 0))
        self.assertEqual(
            self.recorder.sync_checks[0],
            (1, len(b"profile-data-" * 100)),
        )
        self.assertFalse(
            (Path(self.local_dir.name) / "roll" / "a.prof").exists()
        )

    def test_manual_disconnect_then_reconnect_establishes_again(self):
        self.worker.enable()
        self.worker.start()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))

        self.worker.request_disconnect()
        self.assertTrue(
            wait_until(lambda: self.recorder.states[-1] is ConnectionState.DISABLED),
            f"worker did not disable: {self.recorder.states}",
        )

        # The worker closed the old transport; hand it a fresh link like
        # a reopened serial port.
        self.left_sock, self.right_sock = socket.socketpair()
        responder = LoopbackResponder(self.right_sock, Path(self.device_dir.name))
        responder.start()

        self.worker.enable()
        self.assertTrue(
            wait_until(lambda: len(self.recorder.established) > 1),
            "worker did not re-establish after manual disconnect + reconnect",
        )
        self.assertTrue(
            wait_until(lambda: self.recorder.states[-1] is ConnectionState.CONNECTED)
        )


class TestDeleteAfterSync(DeviceConnectionTestBase):
    """Rollview, not the device, removes synced files — and only a full
    sync does it."""

    def _start_device(self):
        self.seed_device_tree()
        self.responder = LoopbackResponder(self.right_sock, Path(self.device_dir.name))
        self.responder.start()
        self.worker.enable()
        self.worker.start()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))
        return Path(self.device_dir.name) / "roll" / "a.prof"

    def _wait_for_sync(self, count):
        self.assertTrue(
            wait_until(lambda: len(self.recorder.sync_finished) >= count),
            f"sync did not finish (failures: {self.recorder.sync_failed})",
        )

    def test_full_sync_removes_fetched_files_from_the_device(self):
        remote = self._start_device()

        self.worker.request_sync(auto=False, delete_remote=True)
        self._wait_for_sync(1)

        fetched, _skipped = self.recorder.sync_finished[0]
        self.assertEqual(fetched, ["roll/a.prof"])
        self.assertEqual(self.recorder.deleted_counts[0], 1)
        self.assertTrue((Path(self.local_dir.name) / "roll" / "a.prof").is_file())
        self.assertFalse(remote.exists())
        # Only files the sync policy covers are removed.
        self.assertTrue((Path(self.device_dir.name) / "roll" / "mean.prof").exists())
        self.assertTrue((Path(self.device_dir.name) / "roll" / "readme.txt").exists())

    def test_full_sync_removes_files_an_earlier_autosync_mirrored(self):
        remote = self._start_device()

        # The post-measurement autosync pulls the file and leaves it.
        self.worker.request_sync(auto=True, incremental=True)
        self._wait_for_sync(1)
        self.assertEqual(self.recorder.deleted_counts[0], 0)
        self.assertTrue(remote.exists())

        # The later full sync fetches nothing but still cleans the device.
        self.worker.request_sync(auto=False, delete_remote=True)
        self._wait_for_sync(2)
        fetched, skipped = self.recorder.sync_finished[1]
        self.assertEqual(fetched, [])
        self.assertEqual(skipped, 1)
        self.assertEqual(self.recorder.deleted_counts[1], 1)
        self.assertFalse(remote.exists())

    def test_incremental_sync_never_deletes_even_when_asked_to(self):
        remote = self._start_device()

        self.worker.request_sync(auto=True, incremental=True, delete_remote=True)
        self._wait_for_sync(1)

        self.assertEqual(self.recorder.deleted_counts[0], 0)
        self.assertTrue(remote.exists())

    def test_device_that_denies_deletes_keeps_its_files(self):
        caps_patch = patch("rqft.demo.CAP_ALLOW_DELETE", 0)
        caps_patch.start()
        self.addCleanup(caps_patch.stop)
        remote = self._start_device()

        self.worker.request_sync(auto=False, delete_remote=True)
        self._wait_for_sync(1)

        # The files still arrive; only the cleanup is skipped.
        self.assertEqual(self.recorder.sync_finished[0][0], ["roll/a.prof"])
        self.assertEqual(self.recorder.deleted_counts[0], 0)
        self.assertTrue(remote.exists())


class TestDoorbellAndBusy(DeviceConnectionTestBase):
    def _start_listening_worker(self):
        self.worker.enable()
        # Keep the worker passive so the doorbell path is exercised
        # instead of the worker's own HELLO.
        self.worker._hello_retry_at = time.monotonic() + 3600
        self.worker.start()
        self.assertTrue(
            wait_until(
                lambda: ConnectionState.LISTENING in self.recorder.states
            ),
            "worker did not reach LISTENING",
        )

    def _ring_doorbell(self):
        """Drive a responder-role HELLO (the doorbell) from the device side."""
        fs = LocalDirFs(self.device_dir.name)
        session = Session(Role.RESPONDER, fs=fs, window=8)
        driver = BlockingSessionDriver(
            SocketTransport(self.right_sock), session, io_timeout_s=0.02
        )
        session.start(driver.now_ms())
        driver.flush()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            events = driver.pump(max_wait_s=0.02).events
            if any(isinstance(event, Established) for event in events):
                return driver
        raise AssertionError("doorbell HELLO was not answered")

    def _send_notify(self, driver, flags):
        """Send a NOTIFY from the device side of an established session."""
        driver.session.send_notify(flags, driver.now_ms())
        driver.flush()

    def test_doorbell_establishes_and_reports_peer_initiated(self):
        self._start_listening_worker()
        self._ring_doorbell()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))
        self.assertTrue(self.recorder.established[0])  # by_doorbell
        self.assertTrue(
            wait_until(lambda: self.recorder.states[-1] is ConnectionState.CONNECTED)
        )

    def test_notify_after_doorbell_forwards_flags(self):
        self._start_listening_worker()
        driver = self._ring_doorbell()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))
        self._send_notify(driver, NOTIFY_SYNC_INCREMENTAL)
        self.assertTrue(wait_until(lambda: len(self.recorder.notify_flags) > 0))
        self.assertEqual(self.recorder.notify_flags[0], NOTIFY_SYNC_INCREMENTAL)

    def test_notify_full_sync_forwards_zero_flags(self):
        self._start_listening_worker()
        driver = self._ring_doorbell()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))
        self._send_notify(driver, 0)
        self.assertTrue(wait_until(lambda: len(self.recorder.notify_flags) > 0))
        self.assertEqual(self.recorder.notify_flags[0], 0)

    def test_notify_after_pc_initiated_establish_forwards_flags(self):
        # The worker initiates the HELLO; the device answers and then sends
        # NOTIFY over the established session (files measured while
        # disconnected), so the sync request reaches RollView either way.
        fs = LocalDirFs(self.device_dir.name)
        session = Session(Role.RESPONDER, fs=fs, window=8)
        driver = BlockingSessionDriver(
            SocketTransport(self.right_sock), session, io_timeout_s=0.02
        )
        self.worker.enable()
        self.worker.start()

        deadline = time.monotonic() + 5.0
        established = False
        while time.monotonic() < deadline and not established:
            events = driver.pump(max_wait_s=0.02).events
            established = any(isinstance(event, Established) for event in events)
        self.assertTrue(established, "worker HELLO was not answered")
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))
        self.assertFalse(self.recorder.established[0])  # self-initiated

        self._send_notify(driver, NOTIFY_SYNC_INCREMENTAL)
        self.assertTrue(wait_until(lambda: len(self.recorder.notify_flags) > 0))
        self.assertEqual(self.recorder.notify_flags[0], NOTIFY_SYNC_INCREMENTAL)

    def test_silent_peer_clears_connected_state(self):
        self._start_listening_worker()
        self._ring_doorbell()
        self.assertTrue(wait_until(lambda: bool(self.recorder.established)))

        # Keep the serial port open but stop servicing the old session,
        # matching a Bluetooth device taken over by another PC.
        with patch("rqft.session.T_DEAD_MS", 200):
            self.assertTrue(
                wait_until(
                    lambda: "dead" in self.recorder.lost
                    and self.recorder.states[-1] is ConnectionState.LISTENING,
                    timeout=2.0,
                ),
                f"silent peer stayed connected: {self.recorder.states}",
            )

    def test_peer_busy_abort_returns_to_listening(self):
        self._start_listening_worker()
        driver = self._ring_doorbell()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))

        # Device starts a measurement: ABORT(E_BUSY) and suspend RQFT.
        driver.abort(AbortReason.E_BUSY)
        self.assertTrue(
            wait_until(lambda: "busy" in self.recorder.lost),
            f"expected busy, got {self.recorder.lost}",
        )
        self.assertTrue(
            wait_until(lambda: self.recorder.states[-1] is ConnectionState.LISTENING)
        )

    def test_busy_during_sync_reports_busy_failure(self):
        self._start_listening_worker()
        driver = self._ring_doorbell()
        self.assertTrue(wait_until(lambda: len(self.recorder.established) > 0))

        self.worker.request_sync(auto=True)
        time.sleep(0.2)
        # Measurement starts mid-sync: the sync fails as busy and the
        # worker goes back to listening for the doorbell.
        driver.abort(AbortReason.E_BUSY)

        self.assertTrue(wait_until(lambda: len(self.recorder.sync_failed) > 0))
        self.assertEqual(self.recorder.sync_failed[0].kind, "busy")
        self.assertTrue(wait_until(lambda: "busy" in self.recorder.lost))
        self.assertTrue(
            wait_until(lambda: self.recorder.states[-1] is ConnectionState.LISTENING)
        )

    def test_unplug_moves_to_open_backoff(self):
        self._start_listening_worker()
        self._simulate_unplugged = True
        self.left_sock.close()
        self.right_sock.close()
        self.assertTrue(
            wait_until(lambda: "unplugged" in self.recorder.lost),
            f"expected unplugged, got {self.recorder.lost}",
        )
        self.assertTrue(
            wait_until(
                lambda: self.recorder.states[-1] is ConnectionState.OPEN_BACKOFF
            )
        )


class TestMultipleDevices(unittest.TestCase):
    """Two devices connected at once: independent sessions, serialized
    syncs through the shared transfer manager."""

    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.local_dir = tempfile.TemporaryDirectory(prefix="rqft-test-local-")
        self.addCleanup(self.local_dir.cleanup)
        self._original_root = store.root_directory
        store.root_directory = self.local_dir.name
        self.addCleanup(lambda: setattr(store, "root_directory", self._original_root))

        # One socketpair + loopback responder per fake port.
        self.transports = {}
        self.responders = []
        for port, folder, filename in (
            ("PORT_A", "roll-a", "a.prof"),
            ("PORT_B", "roll-b", "b.prof"),
        ):
            left, right = socket.socketpair()
            device_dir = tempfile.TemporaryDirectory(prefix=f"rqft-dev-{port}-")
            self.addCleanup(device_dir.cleanup)
            tree = Path(device_dir.name) / folder
            tree.mkdir()
            (tree / filename).write_bytes(f"data-{port}".encode() * 50)
            responder = LoopbackResponder(right, Path(device_dir.name))
            responder.start()
            self.responders.append(responder)
            self.transports[port] = left

        transport_patch = patch(
            "workers.device_connection.SerialTransport",
            side_effect=lambda port, **kwargs: SocketTransport(self.transports[port]),
        )
        transport_patch.start()
        self.addCleanup(transport_patch.stop)

        self.connection_manager = DeviceConnectionManager()
        self.transfer_manager = FileTransferManager()
        self.transfer_manager.set_connection_manager(self.connection_manager)
        self.connection_manager.set_transfer_manager(self.transfer_manager)
        self.addCleanup(self.connection_manager.shutdown_all)

    def _scan_item(self, port, serial_number):
        return SimpleNamespace(
            device=port,
            device_responded=True,
            supports_rqft=True,
            description="Tapio RQP Live",
            serial_number=serial_number,
            firmware_version="v1.2.0",
        )

    def test_two_devices_connect_and_sync_serialized(self):
        self.connection_manager.on_scan_results(
            [self._scan_item("PORT_A", "SN-A"), self._scan_item("PORT_B", "SN-B")]
        )

        # Both auto-connect concurrently, each with its own session.
        self.assertTrue(
            wait_until(
                lambda: self.connection_manager.connection_state("PORT_A")
                is ConnectionState.CONNECTED
                and self.connection_manager.connection_state("PORT_B")
                is ConnectionState.CONNECTED
            ),
            "both devices should reach CONNECTED",
        )
        self.assertEqual(
            set(self.connection_manager.busy_ports()), {"PORT_A", "PORT_B"}
        )

        finished = []
        self.transfer_manager.transferFinished.connect(finished.append)

        # Near-simultaneous sync requests: second is queued, drained
        # after the first finishes.
        self.transfer_manager.request_auto_sync("PORT_A")
        self.transfer_manager.request_auto_sync("PORT_B")

        self.assertTrue(
            wait_until(lambda: len(finished) == 2),
            f"expected two finished transfers, got {finished}",
        )
        root = Path(self.local_dir.name)
        self.assertTrue((root / "roll-a" / "a.prof").is_file())
        self.assertTrue((root / "roll-b" / "b.prof").is_file())
        self.assertFalse(self.transfer_manager.is_transfer_in_progress())
        # Both connections survive their syncs.
        self.assertIs(
            self.connection_manager.connection_state("PORT_A"),
            ConnectionState.CONNECTED,
        )
        self.assertIs(
            self.connection_manager.connection_state("PORT_B"),
            ConnectionState.CONNECTED,
        )


class TestSyncPromptPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.manager = DeviceConnectionManager()
        self.transfer_manager = MagicMock()
        self.transfer_manager.has_pending_sync.return_value = False
        self.manager.set_transfer_manager(self.transfer_manager)
        self.worker = MagicMock()

    def test_prompt_only_after_check_finds_missing_files(self):
        prompts = []
        self.manager.syncPromptRequested.connect(
            lambda port, label: prompts.append((port, label))
        )

        with patch.object(
            self.manager, "get_connection", return_value=self.worker
        ):
            self.manager._on_established("PORT_A", by_doorbell=False)

        self.worker.request_sync_check.assert_called_once_with()
        self.assertEqual(prompts, [])

        self.manager._on_sync_check_finished("PORT_A", 0, 0)
        self.assertEqual(prompts, [])

        self.manager._on_sync_check_finished("PORT_A", 1, 123)
        self.assertEqual(prompts, [("PORT_A", "PORT_A")])

    def test_busy_port_cache_marks_only_connected_session_as_responding(self):
        self.worker.is_alive.return_value = True
        self.worker.enabled = True
        self.manager._workers["PORT_A"] = self.worker
        self.manager.identities["PORT_A"] = DeviceIdentity(
            "Tapio RQP Live", "SN-A", "v1.2.0"
        )

        self.manager._states["PORT_A"] = ConnectionState.CONNECTED
        self.assertTrue(self.manager.busy_ports()["PORT_A"].connected)

        self.manager._states["PORT_A"] = ConnectionState.LISTENING
        self.assertFalse(self.manager.busy_ports()["PORT_A"].connected)


if __name__ == "__main__":
    unittest.main()
