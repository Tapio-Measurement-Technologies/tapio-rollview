"""How the RQFT connection workers share the radio with device discovery.

A Bluetooth worker never pages its own port on a timer: after a failed open
or a lost link it waits for the discovery lane, which pages every Bluetooth
port on one cadence, to say the unit answers. A USB worker keeps its own
backoff, since its opens are instant. The manager reports a waiting
Bluetooth worker's port as free, so the lane may probe it, and does not
poke such a worker on the scan button, so it never pages the port the lane
is about to page.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import settings
from workers.device_connection import (
    ConnectionBridge,
    ConnectionState,
    DeviceConnectionManager,
    DeviceConnectionWorker,
)


def wait_until(condition, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return condition()


class OpenCounter:
    """A transport factory that fails every open and counts the attempts."""

    def __init__(self):
        self.attempts = 0
        self.attempted = threading.Event()

    def __call__(self, *args, **kwargs):
        self.attempts += 1
        self.attempted.set()
        raise OSError("could not open port")


class TestWorkerLeavesBluetoothPagingToDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.opens = OpenCounter()
        patcher = patch("workers.device_connection.SerialTransport", side_effect=self.opens)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._backoffs = settings.RQFT_OPEN_BACKOFF_S
        settings.RQFT_OPEN_BACKOFF_S = (0.05, 0.05)
        self.addCleanup(self._restore_backoffs)

    def _restore_backoffs(self):
        settings.RQFT_OPEN_BACKOFF_S = self._backoffs

    def start_worker(self, bluetooth):
        worker = DeviceConnectionWorker("TESTPORT", ConnectionBridge(), bluetooth=bluetooth)
        worker.enable()
        worker.start()
        self.addCleanup(worker.shutdown)
        self.assertTrue(self.opens.attempted.wait(2.0))
        return worker

    def test_a_bluetooth_worker_opens_once_then_waits_for_discovery(self):
        worker = self.start_worker(bluetooth=True)

        self.assertTrue(wait_until(lambda: worker.awaiting_reachable))
        time.sleep(0.3)

        self.assertEqual(self.opens.attempts, 1)
        self.assertEqual(worker._state, ConnectionState.OPEN_BACKOFF)

    def test_discovery_reporting_the_unit_makes_it_try_again(self):
        worker = self.start_worker(bluetooth=True)
        self.assertTrue(wait_until(lambda: worker.awaiting_reachable))

        worker.enable()   # what the manager does when the lane hears the unit

        self.assertTrue(wait_until(lambda: self.opens.attempts >= 2))
        self.assertTrue(wait_until(lambda: worker.awaiting_reachable))

    def test_retry_now_also_drops_the_wait(self):
        worker = self.start_worker(bluetooth=True)
        self.assertTrue(wait_until(lambda: worker.awaiting_reachable))

        worker.retry_now()

        self.assertTrue(wait_until(lambda: self.opens.attempts >= 2))

    def test_a_usb_worker_keeps_its_own_backoff(self):
        worker = self.start_worker(bluetooth=False)

        self.assertTrue(wait_until(lambda: self.opens.attempts >= 3))
        self.assertFalse(worker.awaiting_reachable)

    def test_a_lost_bluetooth_link_waits_for_discovery_too(self):
        worker = DeviceConnectionWorker("TESTPORT", ConnectionBridge(), bluetooth=True)
        worker.enabled = True
        worker._transport = MagicMock()

        worker._on_transport_error(OSError("unplugged"))

        self.assertTrue(worker.awaiting_reachable)
        self.assertIsNone(worker._transport)


class TestManagerSharesTheRadio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_worker(self, bluetooth, awaiting, enabled=True, alive=True):
        worker = MagicMock()
        worker.bluetooth = bluetooth
        worker.awaiting_reachable = awaiting
        worker.enabled = enabled
        worker.is_alive.return_value = alive
        return worker

    def test_a_bluetooth_worker_waiting_for_discovery_leaves_its_port_free(self):
        manager = DeviceConnectionManager()
        manager._workers["COM6"] = self.make_worker(bluetooth=True, awaiting=True)
        manager._workers["COM7"] = self.make_worker(bluetooth=True, awaiting=False)
        manager._workers["COM1"] = self.make_worker(bluetooth=False, awaiting=False)
        manager._workers["COM2"] = self.make_worker(bluetooth=False, awaiting=False, enabled=False)

        self.assertEqual(sorted(manager.busy_ports()), ["COM1", "COM7"])

    def test_the_scan_button_pokes_every_worker_but_the_ones_discovery_covers(self):
        manager = DeviceConnectionManager()
        waiting = self.make_worker(bluetooth=True, awaiting=True)
        holding = self.make_worker(bluetooth=True, awaiting=False)
        usb = self.make_worker(bluetooth=False, awaiting=False)
        dead = self.make_worker(bluetooth=False, awaiting=False, alive=False)
        manager._workers.update({"COM6": waiting, "COM7": holding, "COM1": usb, "COM3": dead})

        manager.retry_all_now()

        waiting.retry_now.assert_not_called()
        holding.retry_now.assert_called_once()
        usb.retry_now.assert_called_once()
        dead.retry_now.assert_not_called()

    def test_scan_results_tell_the_manager_which_ports_are_bluetooth(self):
        manager = DeviceConnectionManager()
        started = []
        manager._ensure_worker = lambda port: started.append(port)
        item = MagicMock(
            device="COM6", device_responded=True, supports_rqft=True,
            transport="bluetooth", description="Tapio RQP Live",
            serial_number="1", firmware_version="v1.2.0",
        )

        manager.on_scan_results([item])

        self.assertEqual(started, ["COM6"])
        self.assertIn("COM6", manager._bluetooth_ports)

    def test_a_connect_on_a_silent_unit_forgets_the_manual_disconnect(self):
        manager = DeviceConnectionManager()
        manager._manually_disconnected.add("COM6")

        manager.allow_auto_connect("COM6")

        self.assertNotIn("COM6", manager._manually_disconnected)
        self.assertIsNone(manager.connection_state("COM6"))


if __name__ == "__main__":
    unittest.main()
