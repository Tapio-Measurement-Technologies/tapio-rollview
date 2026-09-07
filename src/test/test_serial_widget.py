"""The device panel's Connect and Sync against the discovery lane.

Connect means different things by row: reconnect an RQFT unit, ask a
paired unit that has not answered, and nothing at all on a unit that
answered without RQFT. That last one syncs over ZMODEM, which opens the
port itself, and a connection worker holding the port denied it.
"""

import unittest
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication
from serial.tools import list_ports_common

import settings
from gui.widgets.serialports import SerialWidget
from models.SerialPort import SerialPortItem, SerialPortModel
from utils import preferences
from workers.file_transfer import FileTransferManager


class FakeConnectionManager(QObject):
    connectionStateChanged = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def busy_ports(self):
        return {}

    def connection_state(self, port):
        return None

    def manual_connect(self, port):
        self.calls.append(("manual_connect", port))

    def manual_disconnect(self, port):
        self.calls.append(("manual_disconnect", port))

    def allow_auto_connect(self, port):
        self.calls.append(("allow_auto_connect", port))

    def on_scan_results(self, items):
        self.calls.append(("on_scan_results", [item.device for item in items]))


def make_item(device, responded, firmware="", paired="Tapio RQP Live (1)"):
    info = list_ports_common.ListPortInfo(device, skip_link_detection=True)
    info.description = "Tapio RQP Live"
    info.serial_number = "1"
    info.firmware_version = firmware
    return SerialPortItem(
        info, device_responded=responded, reachable=responded,
        paired_name=paired, transport="bluetooth",
    )


class WidgetCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._prefixes = settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = ("Tapio RQP",)
        self._pinned = preferences.pinned_serial_ports
        preferences.pinned_serial_ports = set()
        self.transfers = FileTransferManager()
        self.connections = FakeConnectionManager()
        self.widget = SerialWidget(self.transfers, self.connections)
        self.widget.scanner.probe_port = MagicMock(return_value=True)
        self.widget.scanner.set_paused = MagicMock()
        self.widget.scanner.wait_until_port_free = MagicMock(return_value=True)

    def tearDown(self):
        self.widget.scanner.stop()
        self.widget.deleteLater()
        self.transfers.deleteLater()
        self.connections.deleteLater()
        QApplication.processEvents()
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = self._prefixes
        preferences.pinned_serial_ports = self._pinned

    def listed(self, item):
        self.widget.view.model.upsertItem(item)
        return item


class TestConnect(WidgetCase):
    def test_a_unit_that_answered_without_rqft_gets_no_connection(self):
        self.listed(make_item("COM6", responded=True, firmware="ac90a85-d"))

        self.widget.connect_device("COM6")

        self.assertEqual(self.connections.calls, [])
        self.widget.scanner.probe_port.assert_not_called()

    def test_an_rqft_unit_is_reconnected(self):
        self.listed(make_item("COM6", responded=True, firmware="v1.2.0"))

        self.widget.connect_device("COM6")

        self.assertEqual(self.connections.calls, [("manual_connect", "COM6")])
        self.widget.scanner.probe_port.assert_not_called()

    def test_a_paired_unit_that_has_not_answered_is_asked_next(self):
        self.listed(make_item("COM10", responded=False))

        self.widget.connect_device("COM10")

        self.assertEqual(self.connections.calls, [("allow_auto_connect", "COM10")])
        self.widget.scanner.probe_port.assert_called_once_with("COM10")


class TestSync(WidgetCase):
    def select(self, item):
        self.widget.view.model.selected_port = item

    def test_sync_pauses_discovery_first_and_waits_for_its_port(self):
        self.select(self.listed(make_item("COM6", responded=True)))
        order = []
        self.widget.scanner.set_paused.side_effect = lambda paused: order.append(("paused", paused))
        self.widget.scanner.wait_until_port_free.side_effect = lambda port, *a: order.append(("waited", port)) or True
        self.transfers.start_transfer = MagicMock(side_effect=lambda *a, **k: order.append(("started",)))
        self.transfers.is_transfer_in_progress = MagicMock(return_value=True)

        self.widget.sync_data()

        self.assertEqual(order, [("paused", True), ("waited", "COM6"), ("started",)])

    def test_discovery_goes_on_when_no_transfer_starts(self):
        self.select(self.listed(make_item("COM6", responded=True)))
        self.transfers.start_transfer = MagicMock()
        self.transfers.is_transfer_in_progress = MagicMock(return_value=False)

        self.widget.sync_data()

        self.assertEqual(
            [call.args for call in self.widget.scanner.set_paused.call_args_list],
            [(True,), (False,)],
        )


class TestBall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._prefixes = settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = ("Tapio RQP",)

    def tearDown(self):
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = self._prefixes

    def ball_for(self, item):
        model = SerialPortModel()
        model.addItem(item)
        model.applyFilter()
        return model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)

    def test_a_paired_unit_that_is_off_shows_a_hollow_ball(self):
        self.assertIsNotNone(self.ball_for(make_item("COM10", responded=False)))

    def test_a_unit_that_answered_without_rqft_shows_no_ball(self):
        self.assertIsNone(self.ball_for(make_item("COM6", responded=True, firmware="ac90a85-d")))

    def test_an_rqft_unit_shows_its_connection_state(self):
        self.assertIsNotNone(self.ball_for(make_item("COM6", responded=True, firmware="v1.2.0")))


if __name__ == "__main__":
    unittest.main()
