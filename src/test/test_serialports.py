"""Device discovery: which ports are asked, in what order, how often.

The lane is driven by hand here: ``step()`` is one unit of work, the clock
is a number the test advances, and every probe is a lookup in a table. That
makes the ordering rules (USB before Bluetooth, the selected unit first,
recent pairings before stale ones, a held port never) plain assertions
rather than timing. The two threaded tests at the end cover the one thing
that cannot be faked: a probe that blocks for as long as Windows makes it.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import settings
from serial.tools import list_ports_common
from utils import preferences
from utils.bluetooth_ports import (
    KIND_BLUETOOTH,
    KIND_BLUETOOTH_INCOMING,
    KIND_OTHER,
    KIND_USB,
    PairedDevice,
    classify_port,
    split_paired_name,
)
from utils.rqft_support import BusyPortStatus, DeviceIdentity
from workers.port_scanner import (
    DiscoveryLane,
    PortScanner,
    probe_port,
    should_probe_port,
)

BT_HWID_PREFIX = "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002\\7&B265825&0&"
BT_INCOMING_HWID = "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\\7&B265825&0&000000000000_00000002"
DAY = 86400.0


def make_port(
    device,
    description="",
    vid=None,
    pid=None,
    serial_number=None,
    hwid="",
    manufacturer=None,
    product=None,
):
    # skip_link_detection: without it pyserial stats the name, and Windows
    # answers a stat of "COM6" by opening the real port behind it.
    port = list_ports_common.ListPortInfo(device, skip_link_detection=True)
    port.description = description
    port.name = device
    port.product = product
    port.manufacturer = manufacturer
    port.hwid = hwid
    port.vid = vid
    port.pid = pid
    port.serial_number = serial_number
    return port


def usb_port(device):
    return make_port(device, vid=0x16C0, pid=0x0483)


def bluetooth_port(device, address):
    return make_port(
        device,
        description=f"Standard Serial over Bluetooth link ({device})",
        hwid=BT_HWID_PREFIX + address + "_C00000000",
    )


def incoming_port(device):
    return make_port(
        device,
        description=f"Standard Serial over Bluetooth link ({device})",
        hwid=BT_INCOMING_HWID,
    )


class FakeSerial:
    def __init__(self, response=b""):
        self.response = response
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def readline(self):
        return self.response

    def close(self):
        self.is_open = False


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RecordingPublisher:
    def __init__(self):
        self.appeared = []
        self.gone = []
        self.results = []
        self.progress_calls = []
        self.finished = []

    def port_appeared(self, item):
        self.appeared.append(item)

    def port_gone(self, device):
        self.gone.append(device)

    def port_result(self, item):
        self.results.append(item)

    def progress(self, percent, text):
        self.progress_calls.append((percent, text))

    def pass_finished(self, items):
        self.finished.append(items)


class SettingsSandbox(unittest.TestCase):
    """Discovery settings pinned to known values, and no pinned ports."""

    def setUp(self):
        self._saved = {
            name: getattr(settings, name)
            for name in (
                "ALLOWED_SERIAL_USB_IDS",
                "SERIAL_BLUETOOTH_PORT_MARKERS",
                "SERIAL_PAIRED_DEVICE_NAME_PREFIXES",
                "DISCOVERY_ENUMERATE_INTERVAL_S",
                "DISCOVERY_EAGER_S",
                "DISCOVERY_RECENT_DAYS",
                "DISCOVERY_STALE_INTERVAL_S",
                "DISCOVERY_BLUETOOTH_GAP_S",
                "DISCOVERY_RETRY_INTERVAL_S",
                "DISCOVERY_LIVE_RECHECK_INTERVAL_S",
            )
        }
        self._saved_pinned = preferences.pinned_serial_ports
        settings.ALLOWED_SERIAL_USB_IDS = {(0x16C0, 0x0483)}
        settings.SERIAL_BLUETOOTH_PORT_MARKERS = ("bluetooth", "bthenum", "bthmodem", "rfcomm")
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = ("Tapio RQP",)
        settings.DISCOVERY_ENUMERATE_INTERVAL_S = 1.5
        settings.DISCOVERY_EAGER_S = 60
        settings.DISCOVERY_RECENT_DAYS = 7
        settings.DISCOVERY_STALE_INTERVAL_S = 60
        settings.DISCOVERY_BLUETOOTH_GAP_S = 0.3
        settings.DISCOVERY_RETRY_INTERVAL_S = 15
        settings.DISCOVERY_LIVE_RECHECK_INTERVAL_S = 60
        preferences.pinned_serial_ports = set()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(settings, name, value)
        preferences.pinned_serial_ports = self._saved_pinned


# -- classification ----------------------------------------------------------

class TestPortClassification(SettingsSandbox):
    def test_usb_vid_pid_candidate_is_probed(self):
        port = usb_port("COM1")
        self.assertEqual(classify_port(port).kind, KIND_USB)
        self.assertTrue(should_probe_port(port, classify_port(port)))

    def test_nonmatching_usb_port_is_not_probed(self):
        port = make_port("COM2", vid=0x1234, pid=0x5678)
        self.assertFalse(should_probe_port(port, classify_port(port)))

    def test_bluetooth_description_candidate_is_probed(self):
        port = make_port("COM3", description="Standard Serial over Bluetooth link")
        port_class = classify_port(port, settings.SERIAL_BLUETOOTH_PORT_MARKERS)
        self.assertEqual(port_class.kind, KIND_BLUETOOTH)
        self.assertIsNone(port_class.address)
        self.assertTrue(should_probe_port(port, port_class))

    def test_outgoing_bluetooth_hwid_carries_the_remote_address(self):
        port = bluetooth_port("COM10", "004B12C02C6A")
        port_class = classify_port(port)
        self.assertEqual(port_class.kind, KIND_BLUETOOTH)
        self.assertEqual(port_class.address, "004B12C02C6A")
        self.assertTrue(should_probe_port(port, port_class))

    def test_incoming_bluetooth_port_is_never_probed(self):
        """Nothing ever calls in on a listening port; RollView is the caller."""
        port = incoming_port("COM11")
        port_class = classify_port(port)
        self.assertEqual(port_class.kind, KIND_BLUETOOTH_INCOMING)
        self.assertFalse(should_probe_port(port, port_class))

    def test_pinned_port_is_probed_whatever_it_looks_like(self):
        preferences.pinned_serial_ports = {"COM4", "COM11"}
        plain = make_port("COM4", description="Standard Serial Port")
        self.assertEqual(classify_port(plain).kind, KIND_OTHER)
        self.assertTrue(should_probe_port(plain, classify_port(plain)))
        # Even an incoming port: pinning is the operator overriding the rule.
        incoming = incoming_port("COM11")
        self.assertTrue(should_probe_port(incoming, classify_port(incoming)))

    def test_paired_name_splits_into_name_and_serial(self):
        self.assertEqual(split_paired_name("Tapio RQP Live (1428495563)"),
                         ("Tapio RQP Live", "1428495563"))
        self.assertEqual(split_paired_name("Headset"), ("Headset", ""))
        self.assertEqual(split_paired_name(""), ("", ""))


# -- one probe ---------------------------------------------------------------

class TestProbePort(SettingsSandbox):
    @patch("workers.port_scanner.send_timestamp")
    @patch("workers.port_scanner.serial.Serial")
    def test_invalid_response_does_not_mark_device_responded(self, mock_serial, mock_send_timestamp):
        mock_serial.return_value = FakeSerial(b'{"deviceName": "Tapio RQP Live"}\n')

        _port_info, device_responded, _error = probe_port(usb_port("COM1"))

        self.assertFalse(device_responded)
        mock_send_timestamp.assert_not_called()

    @patch("workers.port_scanner.send_timestamp")
    @patch("workers.port_scanner.serial.Serial")
    def test_firmware_version_is_read_from_deviceinfo(self, mock_serial, mock_send_timestamp):
        mock_serial.return_value = FakeSerial(
            b'{"deviceName": "Tapio RQP Live", "serialNumber": "ABC123",'
            b' "firmwareVersion": "v1.2.0"}\n'
        )

        port_info, device_responded, _error = probe_port(usb_port("COM1"))

        self.assertTrue(device_responded)
        self.assertEqual(port_info.firmware_version, "v1.2.0")
        self.assertEqual(port_info.serial_number, "ABC123")
        mock_send_timestamp.assert_called_once()

    @patch("workers.port_scanner.serial.Serial")
    def test_open_failure_is_reported_not_raised(self, mock_serial):
        mock_serial.side_effect = OSError("could not open port")

        _port_info, device_responded, error = probe_port(usb_port("COM1"))

        self.assertFalse(device_responded)
        self.assertIn("could not open", error)

    @patch("workers.port_scanner.serial.Serial")
    def test_a_shutdown_during_the_open_sends_nothing(self, mock_serial):
        """The open can block for seconds; a stop that lands meanwhile must
        not be followed by a command on the wire."""
        fake = FakeSerial(b'{"deviceName": "x", "serialNumber": "1"}\n')
        mock_serial.return_value = fake
        checks = []

        def running():
            # Alive before the open, stopped by the time it returns.
            checks.append(True)
            return len(checks) == 1

        _port_info, responded, error = probe_port(usb_port("COM1"), running=running)

        self.assertFalse(responded)
        self.assertEqual(error, "Scan cancelled")
        self.assertEqual(fake.writes, [])
        self.assertFalse(fake.is_open)


# -- the lane, by hand -------------------------------------------------------

class LaneHarness(SettingsSandbox):
    """A lane with a hand-driven clock, a port table and a probe table."""

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.wall = 1_700_000_000.0
        self.ports = []
        self.paired = {}
        self.busy = {}
        self.responses = {}
        self.probed = []
        self.publisher = RecordingPublisher()
        self.lane = DiscoveryLane(
            self.publisher,
            busy_ports=lambda: dict(self.busy),
            clock=self.clock,
            wall_clock=lambda: self.wall,
            comports=lambda: list(self.ports),
            paired=lambda: dict(self.paired),
            probe=self._probe,
        )

    def _probe(self, info, running):
        self.probed.append(info.device)
        response = self.responses.get(info.device)
        if response is None:
            return info, False, "could not open port"
        info.description, info.serial_number, info.firmware_version = response
        return info, True, None

    def pair(self, address, name, used_days_ago=None):
        last_used = None if used_days_ago is None else self.wall - used_days_ago * DAY
        self.paired[address] = PairedDevice(address, name, last_used, False)

    def run_pass(self, limit=50):
        """A scan request, then steps until the pass has finished."""
        self.lane.scan_now()
        for _ in range(limit):
            if self.publisher.finished:
                return
            if not self.lane.step():
                # Nothing eligible right now: let the radio gap pass.
                self.clock.advance(settings.DISCOVERY_BLUETOOTH_GAP_S)
        self.fail("the pass never finished")

    def steps(self, count, limit=20):
        """Run until ``count`` probes have happened, letting the radio gap
        pass whenever a step finds nothing to do. Gives up after ``limit``
        idle steps, so a paused lane simply comes back with nothing."""
        idle = 0
        while count > 0 and idle < limit:
            if self.lane.step():
                count -= 1
            else:
                idle += 1
                self.clock.advance(settings.DISCOVERY_BLUETOOTH_GAP_S)


class TestEnumeration(LaneHarness):
    def test_every_port_is_listed_before_anything_is_probed(self):
        self.ports = [usb_port("COM1"), bluetooth_port("COM10", "004B12C02C6A"), incoming_port("COM11")]
        self.pair("004B12C02C6A", "Tapio RQP Live (2748487262)", used_days_ago=1)

        self.lane._refresh()

        self.assertEqual([item.device for item in self.publisher.appeared], ["COM1", "COM10", "COM11"])
        self.assertEqual(self.probed, [])
        unit = self.publisher.appeared[1]
        self.assertEqual(unit.description, "Tapio RQP Live")
        self.assertEqual(unit.serial_number, "2748487262")
        self.assertIsNone(unit.reachable)
        self.assertFalse(unit.device_responded)
        self.assertTrue(unit.is_paired_unit())
        self.assertEqual(unit.transport, KIND_BLUETOOTH)
        self.assertEqual(unit.bluetooth_address, "004B12C02C6A")

    def test_a_port_that_disappears_is_reported_gone(self):
        self.ports = [usb_port("COM1"), usb_port("COM2")]
        self.lane._refresh()
        self.ports = [usb_port("COM2")]

        self.lane._refresh()

        self.assertEqual(self.publisher.gone, ["COM1"])
        self.assertEqual(sorted(self.lane._cands), ["COM2"])

    def test_a_missing_pinned_port_is_listed_and_probed(self):
        preferences.pinned_serial_ports = {"COM9"}
        self.ports = []

        self.run_pass()

        self.assertEqual([item.device for item in self.publisher.appeared], ["COM9"])
        self.assertEqual(self.probed, ["COM9"])

    def test_enumeration_failure_keeps_the_table(self):
        self.ports = [usb_port("COM1")]
        self.lane._refresh()

        def boom():
            raise RuntimeError("enumeration exploded")
        self.lane._comports = boom
        self.lane._refresh()

        self.assertEqual(sorted(self.lane._cands), ["COM1"])
        self.assertEqual(self.publisher.gone, [])

    def test_a_new_usb_port_is_probed_on_the_next_step(self):
        self.ports = [usb_port("COM1")]
        self.responses["COM1"] = ("Tapio RQP Live", "USB1", "v1.2.0")
        self.lane._refresh()

        self.assertTrue(self.lane.step())

        self.assertEqual(self.probed, ["COM1"])
        result = self.publisher.results[-1]
        self.assertTrue(result.device_responded)
        self.assertEqual(result.serial_number, "USB1")
        self.assertTrue(result.supports_rqft)


class TestPassOrdering(LaneHarness):
    def test_a_pass_probes_candidates_only_and_in_priority_order(self):
        self.ports = [
            bluetooth_port("COM13", "142B2FADB826"),   # stale pairing
            make_port("COM2", vid=0x1234, pid=0x5678),   # not ours
            incoming_port("COM11"),
            bluetooth_port("COM6", "004B12C02EFE"),    # used yesterday
            usb_port("COM1"),
        ]
        self.pair("142B2FADB826", "Tapio RQP Live (1683535058)", used_days_ago=80)
        self.pair("004B12C02EFE", "Tapio RQP Live (1428495563)", used_days_ago=1)
        self.responses["COM6"] = ("Tapio RQP Live", "1428495563", "v1.2.0")

        self.run_pass()

        # Instant opens first, then the recent pairing, then the stale one.
        self.assertEqual(self.probed, ["COM1", "COM6", "COM13"])
        self.assertEqual(len(self.publisher.finished), 1)
        self.assertEqual(
            [(p, t.split("(")[1]) for p, t in self.publisher.progress_calls],
            [(33, "1/3)"), (66, "2/3)"), (100, "3/3)")],
        )
        by_device = {item.device: item for item in self.publisher.finished[0]}
        self.assertEqual(sorted(by_device), ["COM1", "COM11", "COM13", "COM2", "COM6"])
        self.assertTrue(by_device["COM6"].device_responded)
        self.assertFalse(by_device["COM13"].device_responded)
        self.assertIs(by_device["COM13"].reachable, False)
        self.assertIsNone(by_device["COM11"].reachable)

    def test_the_selected_port_goes_first(self):
        self.ports = [usb_port("COM1"), bluetooth_port("COM6", "004B12C02EFE")]
        self.lane.set_preferred("COM6")

        self.run_pass()

        # Even ahead of the instant USB open: it is what the operator is
        # looking at.
        self.assertEqual(self.probed[0], "COM6")

    def test_a_pinned_port_goes_before_recent_pairings(self):
        preferences.pinned_serial_ports = {"COM13"}
        self.ports = [bluetooth_port("COM6", "004B12C02EFE"), bluetooth_port("COM13", "142B2FADB826")]
        self.pair("004B12C02EFE", "Tapio RQP Live (1428495563)", used_days_ago=1)

        self.run_pass()

        self.assertEqual(self.probed, ["COM13", "COM6"])

    def test_a_held_port_is_never_probed_and_is_reported_from_its_worker(self):
        preferences.pinned_serial_ports = {"COM7"}
        self.ports = [usb_port("COM7"), usb_port("COM1")]
        self.busy["COM7"] = BusyPortStatus(
            DeviceIdentity("Tapio RQP Live", "ABC123", "v1.2.0"), connected=True
        )

        self.run_pass()

        self.assertEqual(self.probed, ["COM1"])
        held = next(item for item in self.publisher.results if item.device == "COM7")
        self.assertTrue(held.device_responded)
        self.assertEqual(held.serial_number, "ABC123")
        self.assertTrue(held.supports_rqft)

    def test_a_held_port_whose_session_is_down_is_known_but_not_responding(self):
        self.ports = [usb_port("COM7")]
        self.busy["COM7"] = BusyPortStatus(
            DeviceIdentity("Tapio RQP Live", "ABC123", "v1.2.0"), connected=False
        )

        self.run_pass()

        self.assertEqual(self.probed, [])
        held = self.publisher.results[0]
        self.assertFalse(held.device_responded)
        self.assertTrue(held.supports_rqft)
        self.assertEqual(held.description, "Tapio RQP Live")

    def test_a_pass_with_nothing_to_probe_still_finishes(self):
        self.ports = [make_port("COM2", vid=0x1234, pid=0x5678)]

        self.run_pass()

        self.assertEqual(self.probed, [])
        self.assertEqual(self.publisher.progress_calls, [(100, "Scanning complete")])
        self.assertEqual(len(self.publisher.finished), 1)

    def test_a_port_taken_by_a_worker_mid_pass_does_not_hold_the_pass_open(self):
        self.ports = [bluetooth_port("COM6", "004B12C02EFE"), bluetooth_port("COM13", "142B2FADB826")]
        self.lane.scan_now()
        self.assertTrue(self.lane.step())          # probes one
        taken = next(d for d in ("COM6", "COM13") if d not in self.probed)
        self.busy[taken] = None

        self.clock.advance(1)
        self.lane.step()

        self.assertEqual(len(self.publisher.finished), 1)
        self.assertNotIn(taken, self.probed)

    def test_stopping_a_pass_reports_it_finished_exactly_once_and_ends_eagerness(self):
        """Stop is the operator asking for the radio to be left alone: the
        pass ends, and stale pairings go back to their slow cadence."""
        self.ports = [bluetooth_port("COM6", "004B12C02EFE"), bluetooth_port("COM13", "142B2FADB826")]
        self.lane.scan_now()
        self.assertTrue(self.lane.step())

        self.lane.stop_pass()
        self.lane.stop_pass()
        self.steps(4)

        self.assertEqual(len(self.publisher.finished), 1)
        # The one owed at the time completed and is not asked again before
        # its minute is up. The other had never been asked, so it gets its
        # one first-sight probe, outside the pass and without progress.
        self.assertEqual(self.probed.count("COM6"), 1)
        self.assertLessEqual(self.probed.count("COM13"), 1)
        self.assertEqual(len(self.publisher.progress_calls), 1)
        self.clock.advance(settings.DISCOVERY_STALE_INTERVAL_S + 1)
        self.probed.clear()
        self.steps(2)
        self.assertEqual(sorted(self.probed), ["COM13", "COM6"])


class TestCadence(LaneHarness):
    def setUp(self):
        super().setUp()
        self.ports = [bluetooth_port("COM6", "004B12C02EFE"), bluetooth_port("COM13", "142B2FADB826")]
        self.pair("004B12C02EFE", "Tapio RQP Live (1428495563)", used_days_ago=1)
        self.pair("142B2FADB826", "Tapio RQP Live (1683535058)", used_days_ago=80)
        self.lane._refresh()

    def probe_of(self, device):
        return self.lane._cands[device]

    def test_first_sight_is_probed_eagerly_whatever_its_age(self):
        self.steps(2)
        self.assertEqual(sorted(self.probed), ["COM13", "COM6"])

    def test_a_recent_pairing_probed_back_to_back_does_not_starve_a_stale_one(self):
        """Both are off. The recent one is asked again and again; the stale
        one still gets its turn when its minute is up."""
        self.steps(2)
        self.probed.clear()
        self.clock.advance(settings.DISCOVERY_STALE_INTERVAL_S + 1)

        self.steps(6)

        self.assertIn("COM13", self.probed)
        self.assertGreater(self.probed.count("COM6"), self.probed.count("COM13"))

    def test_a_recent_pairing_is_probed_back_to_back_while_absent(self):
        self.steps(2)
        gap = self.probe_of("COM6").next_due - self.clock()
        self.assertLessEqual(gap, settings.DISCOVERY_BLUETOOTH_GAP_S)

    def test_a_stale_pairing_waits_the_stale_interval(self):
        self.steps(2)
        wait = self.probe_of("COM13").next_due - self.clock()
        self.assertGreater(wait, settings.DISCOVERY_STALE_INTERVAL_S - 1)

    def test_eager_mode_makes_a_stale_pairing_continuous(self):
        self.lane.scan_now()
        self.run_pass()
        wait = self.probe_of("COM13").next_due - self.clock()
        self.assertLessEqual(wait, settings.DISCOVERY_BLUETOOTH_GAP_S)

        # ...until the eager window closes. The one probe already scheduled
        # still runs; the one after it is a minute away.
        self.clock.advance(settings.DISCOVERY_EAGER_S + 1)
        self.probed.clear()
        self.steps(4)
        self.assertLessEqual(self.probed.count("COM13"), 1)
        self.assertGreaterEqual(self.probed.count("COM6"), 3)
        wait = self.probe_of("COM13").next_due - self.clock()
        self.assertGreater(wait, settings.DISCOVERY_STALE_INTERVAL_S - 2)

    def test_a_unit_that_answered_is_rechecked_slowly(self):
        self.responses["COM6"] = ("Tapio RQP Live", "1428495563", "v1.2.0")
        self.steps(2)
        wait = self.probe_of("COM6").next_due - self.clock()
        self.assertGreater(wait, settings.DISCOVERY_LIVE_RECHECK_INTERVAL_S - 1)

    def test_a_unit_that_answered_this_session_counts_as_recent_afterwards(self):
        self.responses["COM13"] = ("Tapio RQP Live", "1683535058", "v1.2.0")
        self.steps(2)
        del self.responses["COM13"]
        self.clock.advance(settings.DISCOVERY_LIVE_RECHECK_INTERVAL_S + 1)
        self.probed.clear()
        self.steps(2)

        self.assertIn("COM13", self.probed)
        wait = self.probe_of("COM13").next_due - self.clock()
        self.assertLessEqual(wait, settings.DISCOVERY_BLUETOOTH_GAP_S)

    def test_two_bluetooth_probes_keep_the_radio_gap(self):
        self.assertTrue(self.lane.step())
        # Same instant: the second Bluetooth port has to wait for the gap.
        self.assertFalse(self.lane.step())
        self.clock.advance(settings.DISCOVERY_BLUETOOTH_GAP_S)
        self.assertTrue(self.lane.step())
        self.assertEqual(len(self.probed), 2)

    def test_a_usb_port_is_not_held_up_by_the_radio_gap(self):
        self.ports.append(usb_port("COM1"))
        self.lane._next_enum = 0
        self.assertTrue(self.lane.step())   # enumerates, probes the USB port first
        self.assertEqual(self.probed, ["COM1"])
        self.assertTrue(self.lane.step())   # then a Bluetooth port
        self.assertFalse(self.lane.step())  # the other waits for the gap

    def test_a_held_port_that_comes_due_is_pushed_out_not_spun_on(self):
        self.busy["COM6"] = None
        self.busy["COM13"] = None
        self.assertFalse(self.lane.step())
        self.assertGreaterEqual(
            self.lane._idle_wait_locked(), min(0.3, settings.DISCOVERY_ENUMERATE_INTERVAL_S)
        )
        self.assertEqual(self.probed, [])

    def test_a_probe_request_jumps_the_queue(self):
        self.steps(2)
        self.clock.advance(1)
        self.probed.clear()

        self.assertTrue(self.lane.probe_now("COM13"))
        self.steps(1)

        self.assertEqual(self.probed, ["COM13"])
        self.assertFalse(self.lane.probe_now("COM99"))

    def test_paused_probes_nothing_until_unpaused(self):
        self.lane.set_paused(True)
        self.steps(3)
        self.assertEqual(self.probed, [])
        self.lane.set_paused(False)
        self.steps(1)
        self.assertEqual(len(self.probed), 1)

    def test_a_probe_that_raises_does_not_end_the_lane(self):
        def broken(info, running):
            raise RuntimeError("driver fell over")
        self.lane._probe = broken

        self.assertTrue(self.lane.step())

        result = self.publisher.results[-1]
        self.assertFalse(result.device_responded)
        self.assertIs(result.reachable, False)

    def test_a_busy_lookup_that_raises_probes_nothing(self):
        def broken():
            raise RuntimeError("manager gone")
        self.lane._busy_ports = broken

        self.assertFalse(self.lane.step())
        self.assertEqual(self.probed, [])


# -- the thread ----------------------------------------------------------------

class BlockingProbe:
    """A probe that blocks until released, the way a Bluetooth page does."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, info, running):
        self.calls += 1
        self.entered.set()
        self.release.wait(5.0)
        return info, False, "could not open port"


class TestLaneThread(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._saved_pinned = preferences.pinned_serial_ports
        preferences.pinned_serial_ports = set()

    def tearDown(self):
        preferences.pinned_serial_ports = self._saved_pinned

    def make_scanner(self, probe):
        scanner = PortScanner()
        lane = scanner._lane
        lane._comports = lambda: [usb_port("COM1")]
        lane._paired = lambda: {}
        lane._probe = probe
        self.addCleanup(scanner.stop, 6000)
        return scanner

    def test_stop_waits_for_a_blocked_probe_and_reports_the_wait_honestly(self):
        probe = BlockingProbe()
        scanner = self.make_scanner(probe)

        scanner.scan_now()
        self.assertTrue(probe.entered.wait(2.0))
        self.assertTrue(scanner.is_running())

        # A page cannot be cut short: a stop that times out says so.
        self.assertFalse(scanner.stop(timeout_ms=200))
        self.assertTrue(scanner.is_running())

        probe.release.set()
        self.assertTrue(scanner.stop(timeout_ms=3000))
        self.assertFalse(scanner.is_running())
        self.assertEqual(probe.calls, 1)

    def test_wait_until_port_free_is_bounded_while_a_probe_blocks(self):
        probe = BlockingProbe()
        scanner = self.make_scanner(probe)
        scanner.scan_now()
        self.assertTrue(probe.entered.wait(2.0))

        started = time.monotonic()
        self.assertFalse(scanner.wait_until_port_free("COM1", timeout_s=0.3))
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(scanner.wait_until_port_free("COM2", timeout_s=0.3))

        probe.release.set()
        self.assertTrue(scanner.wait_until_port_free("COM1", timeout_s=3.0))

    def test_every_event_reaches_the_gui_thread_as_a_signal(self):
        """The real Qt object, through the event loop: what the widget gets.

        The lane thread cannot call a signal; a publisher that tried would
        raise on every event and the list would stay empty while the log
        filled up. This is the test that notices.
        """
        def probe(info, running):
            info.description, info.serial_number, info.firmware_version = (
                "Tapio RQP Live", "USB1", "v1.2.0")
            return info, True, None

        scanner = self.make_scanner(probe)
        events = []
        scanner.port_appeared.connect(lambda item: events.append(("appeared", item.device)))
        scanner.port_result.connect(lambda item: events.append(("result", item.device, item.device_responded)))
        scanner.progress.connect(lambda percent, text: events.append(("progress", percent)))
        scanner.finished.connect(lambda items: events.append(("finished", len(items))))

        scanner.scan_now()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and ("finished", 1) not in events:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        self.assertEqual(events, [
            ("appeared", "COM1"),
            ("progress", 100),
            ("result", "COM1", True),
            ("finished", 1),
        ])

    def test_stop_is_safe_before_start_and_twice_after(self):
        scanner = PortScanner()
        self.assertTrue(scanner.stop())
        self.assertFalse(scanner.is_running())
        scanner.start()
        self.assertTrue(scanner.is_running())
        self.assertTrue(scanner.stop())
        self.assertTrue(scanner.stop())
        self.assertFalse(scanner.is_running())

    def test_a_stopped_lane_can_be_started_again(self):
        probe = MagicMock(side_effect=lambda info, running: (info, False, "no"))
        scanner = self.make_scanner(probe)
        scanner.start()
        self.assertTrue(scanner.stop())
        scanner.start()
        self.assertTrue(scanner.is_running())


if __name__ == "__main__":
    unittest.main()
