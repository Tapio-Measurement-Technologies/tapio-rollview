"""The connection worker's port is configured once and never touched again.

pyserial writes the whole port configuration back to the driver whenever
its timeout is assigned, and the unit reads such a write as its cable being
replugged. So the transport must never set the timeout after the open,
whatever wait a read asks for.
"""

import unittest
from unittest.mock import patch

from utils.serial_transport import READ_SLICE_S, SteadySerialTransport


class FakeSerial:
    """Enough of serial.Serial to see what the transport does to it."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._timeout = kwargs.get("timeout")
        self.timeout_assignments = 0
        self.pending = b""
        self.reads = []

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self.timeout_assignments += 1
        self._timeout = value

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, size):
        self.reads.append(size)
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def write(self, data):
        return len(data)

    def close(self):
        pass


class TestSteadySerialTransport(unittest.TestCase):
    def open(self, **kwargs):
        with patch("utils.serial_transport.serial.Serial", side_effect=FakeSerial) as factory:
            transport = SteadySerialTransport("COM9", write_timeout=5.0, **kwargs)
        self.fake = factory.side_effect
        return transport

    def setUp(self):
        self.created = []

        def make(**kwargs):
            fake = FakeSerial(**kwargs)
            self.created.append(fake)
            return fake

        patcher = patch("utils.serial_transport.serial.Serial", side_effect=make)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_port_is_opened_with_one_short_read_slice(self):
        SteadySerialTransport("COM9", write_timeout=5.0)

        fake = self.created[0]
        self.assertEqual(fake.kwargs["port"], "COM9")
        self.assertEqual(fake.kwargs["timeout"], READ_SLICE_S)
        self.assertEqual(fake.kwargs["write_timeout"], 5.0)

    def test_reads_never_assign_the_timeout(self):
        transport = SteadySerialTransport("COM9")
        fake = self.created[0]

        fake.pending = b"abc"
        self.assertEqual(transport.read(64, 0.05), b"abc")
        self.assertEqual(transport.read(64, 0.0), b"")
        self.assertEqual(transport.read(64, 0.02), b"")

        self.assertEqual(fake.timeout_assignments, 0)

    def test_a_wait_of_zero_takes_only_what_has_arrived(self):
        transport = SteadySerialTransport("COM9")
        fake = self.created[0]
        fake.pending = b"hello"

        self.assertEqual(transport.read(3, 0.0), b"hel")
        self.assertEqual(fake.reads, [3])

    def test_a_longer_wait_is_a_loop_of_slices_that_ends_at_the_first_bytes(self):
        transport = SteadySerialTransport("COM9")
        fake = self.created[0]

        original_read = fake.read

        def read_after_two_slices(size):
            if len(fake.reads) == 2:
                fake.pending = b"late"
            return original_read(size)

        fake.read = read_after_two_slices
        self.assertEqual(transport.read(64, 1.0), b"late")
        self.assertEqual(len(fake.reads), 3)

    def test_a_wait_with_nothing_arriving_returns_empty_once_it_is_over(self):
        transport = SteadySerialTransport("COM9")
        fake = self.created[0]

        self.assertEqual(transport.read(64, 0.02), b"")
        self.assertGreaterEqual(len(fake.reads), 1)


if __name__ == "__main__":
    unittest.main()
