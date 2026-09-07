"""The device panel's Connect and Sync against the discovery lane.

Connect means different things by row: reconnect an RQFT unit, ask a
paired unit that has not answered, and nothing at all on a unit that
answered without RQFT. That last one syncs over ZMODEM, which opens the
port itself, and a connection worker holding the port denied it.
"""

import unittest
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from serial.tools import list_ports_common

import settings
from gui.widgets.serialports import SerialWidget
from models.SerialPort import (
    BALL_ABSENT,
    BALL_LIVE,
    BALL_READY,
    BALL_WORKING,
    SerialPortItem,
    SerialPortModel,
    _ball_icon,
)
from test.qtcleanup import destroy
from utils import preferences
from workers.device_connection import ConnectionState
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
        self.transfers.deleteLater()
        self.connections.deleteLater()
        # deleteLater alone leaves the widget alive until something drains
        # the queue, and --leakcheck counts what is still standing.
        destroy(self.widget)
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
    """The ball answers one question for every device: can I sync from
    this now? Fill says the device is there, colour says how ready."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._prefixes = settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = ("Tapio RQP",)
        self._pinned = preferences.pinned_serial_ports
        preferences.pinned_serial_ports = set()

    def tearDown(self):
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = self._prefixes
        preferences.pinned_serial_ports = self._pinned

    def model_for(self, item, state=None):
        model = SerialPortModel()
        model.addItem(item)
        model.applyFilter()
        model.connection_state_provider = lambda device: state
        return model

    def kind_for(self, item, state=None):
        return self.model_for(item, state).ballKind(item)

    def test_a_device_that_answered_without_rqft_is_ready_not_blank(self):
        """It syncs on the button like any other; it just holds no
        connection. Showing nothing beside it left the one device that
        works looking like the one row with nothing to say."""
        item = make_item("COM6", responded=True, firmware="ac90a85-d")

        self.assertEqual(self.kind_for(item), BALL_READY)
        self.assertIsNotNone(
            self.model_for(item).data(self.model_for(item).index(0, 0),
                                      Qt.ItemDataRole.DecorationRole))

    def test_a_paired_unit_that_is_off_is_absent(self):
        self.assertEqual(self.kind_for(make_item("COM10", responded=False)), BALL_ABSENT)

    def test_an_rqft_device_shows_its_connection(self):
        item = make_item("COM6", responded=True, firmware="v1.2.0")

        self.assertEqual(self.kind_for(item, ConnectionState.CONNECTED), BALL_LIVE)
        self.assertEqual(self.kind_for(item, ConnectionState.CONNECTING), BALL_WORKING)
        self.assertEqual(self.kind_for(item, ConnectionState.LISTENING), BALL_WORKING)
        self.assertEqual(self.kind_for(item, ConnectionState.OPEN_BACKOFF), BALL_WORKING)

    def test_an_rqft_device_the_operator_disconnected_is_still_ready(self):
        """Sync still works on it, which is what the ball is about."""
        item = make_item("COM6", responded=True, firmware="v1.2.0")

        self.assertEqual(self.kind_for(item, ConnectionState.DISABLED), BALL_READY)

    def test_a_port_that_is_not_a_device_gets_no_ball(self):
        """With every COM port listed, a ball on each would decorate
        modems and label printers with an answer to a question nobody
        asked of them."""
        item = make_item("COM3", responded=False, paired="")

        self.assertIsNone(self.kind_for(item))

    def test_a_pinned_port_is_a_device_row_even_before_it_answers(self):
        preferences.pinned_serial_ports = {"COM3"}
        item = make_item("COM3", responded=False, paired="")

        self.assertEqual(self.kind_for(item), BALL_ABSENT)

    def test_selecting_a_row_does_not_wash_out_its_ball(self):
        """A selected row has its decoration tinted towards the highlight by
        the style, and this ball is not decoration: the colour is the whole
        of what it says. The row an operator has selected is the one they
        are about to sync from, which makes it the worst one to fade."""
        for kind in (BALL_ABSENT, BALL_READY, BALL_WORKING, BALL_LIVE):
            with self.subTest(kind=kind):
                icon = _ball_icon(kind)
                size = icon.availableSizes()[0]
                self.assertEqual(
                    icon.pixmap(size, QIcon.Mode.Normal).toImage(),
                    icon.pixmap(size, QIcon.Mode.Selected).toImage(),
                )

    def test_the_ball_colours_come_from_the_token_table(self):
        """The design system's rule: a colour written anywhere else is a
        bug. The icons used to carry their own hex."""
        import inspect

        import models.SerialPort as module

        source = inspect.getsource(module)
        self.assertNotRegex(source, r"#[0-9a-fA-F]{6}")

    def test_every_state_says_in_the_row_what_its_ball_means(self):
        item = make_item("COM6", responded=True, firmware="v1.2.0")

        self.assertIn("Ready", self.model_for(item, ConnectionState.DISABLED).guidance_for(item))
        self.assertIn("Connecting", self.model_for(item, ConnectionState.CONNECTING).guidance_for(item))
        self.assertIn("Connected", self.model_for(item, ConnectionState.CONNECTED).guidance_for(item))


class TestRowText(unittest.TestCase):
    """A device row says one line, in the status row, and it is a label
    rather than a sentence about the device. Pointing at a device used to
    put the whole fault and its remedy there."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._prefixes = settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = ("Tapio RQP",)

    def tearDown(self):
        settings.SERIAL_PAIRED_DEVICE_NAME_PREFIXES = self._prefixes

    def data_for(self, item, role):
        model = SerialPortModel()
        model.addItem(item)
        model.applyFilter()
        return model.data(model.index(0, 0), role)

    def test_the_status_row_names_the_state_without_the_remedy(self):
        tip = self.data_for(make_item("COM10", responded=False),
                            Qt.ItemDataRole.StatusTipRole)

        self.assertIn("COM10", tip)
        self.assertIn("Not connected", tip)
        self.assertNotIn("in range", tip)
        self.assertNotIn("\n", tip)
        self.assertLess(len(tip), 90)

    def test_a_device_row_has_no_tooltip_of_its_own(self):
        """The status row says it, and it is short enough to be all there
        is to say. A second surface for the same row is one to keep in
        step with it for nothing."""
        self.assertIsNone(self.data_for(make_item("COM10", responded=False),
                                        Qt.ItemDataRole.ToolTipRole))

    def test_a_device_that_answers_says_only_what_can_be_done_with_it(self):
        tip = self.data_for(make_item("COM6", responded=True, firmware="v1.2.0"),
                            Qt.ItemDataRole.StatusTipRole)

        self.assertIn("COM6", tip)
        self.assertNotIn("Serial number", tip)


if __name__ == "__main__":
    unittest.main()
