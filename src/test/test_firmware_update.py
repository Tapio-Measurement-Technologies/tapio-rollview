"""The firmware update path, with nothing on the bus.

The image parser and checks are pure. The updater talks to the device
through seams a fake stands behind here: a bootloader that refuses writes
while busy, a restart request that makes it appear, and a running port
that comes back after the reboot command.
"""

import unittest

from utils.firmware_image import (
    DEVICE_FLASH_SIZE,
    FLASH_BASE,
    FirmwareImageError,
    check_device_image,
    parse_intel_hex,
)
from utils.firmware_update import (
    BLOCK_SIZE,
    REPORT_SIZE,
    BootloaderDevice,
    FirmwareUpdateError,
    FirmwareUpdater,
    block_report,
    plan_blocks,
    reboot_report,
)


def hex_record(rtype, offset, data):
    body = bytes([len(data)]) + offset.to_bytes(2, "big") + bytes([rtype]) + data
    checksum = (-sum(body)) & 0xFF
    return ":" + (body + bytes([checksum])).hex().upper()


def device_hex(payload=b"", flash_size=DEVICE_FLASH_SIZE, base=FLASH_BASE):
    """An Intel HEX file shaped like the device's own: the flash
    configuration block at the flash base, then ``payload`` after it."""
    config = bytearray(512)
    config[0:8] = (0x5601000042464346).to_bytes(8, "little")
    config[80:84] = flash_size.to_bytes(4, "little")
    data = bytes(config) + payload
    lines = []
    upper = None
    for offset in range(0, len(data), 16):
        address = base + offset
        if address >> 16 != upper:
            upper = address >> 16
            lines.append(hex_record(0x04, 0, upper.to_bytes(2, "big")))
        lines.append(hex_record(0x00, address & 0xFFFF, data[offset:offset + 16]))
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


class TestIntelHex(unittest.TestCase):
    def test_a_device_file_parses_to_its_flash_addresses(self):
        image = parse_intel_hex(device_hex(b"\x01\x02\x03"))

        self.assertEqual(image.min_address, FLASH_BASE)
        self.assertEqual(image.max_address, FLASH_BASE + 512 + 3)
        head, filled = image.read(FLASH_BASE, 8)
        self.assertEqual(filled, 8)
        self.assertEqual(head, b"FCFB\x00\x01\x01\x56"[:4] + b"\x00\x00\x01\x56")

    def test_a_bad_checksum_fails_the_whole_file(self):
        text = device_hex(b"\x01")
        broken = text.replace(":00000001FF", ":0100000000FE\n:00000001FF")

        with self.assertRaises(FirmwareImageError):
            parse_intel_hex(broken)

    def test_something_that_is_not_hex_is_refused(self):
        with self.assertRaises(FirmwareImageError):
            parse_intel_hex("MZ\x90\x00 this is an exe")

    def test_reading_across_a_gap_fills_with_zeros(self):
        text = "\n".join([
            hex_record(0x04, 0, b"\x60\x00"),
            hex_record(0x00, 0x0000, b"\xAA\xBB"),
            hex_record(0x00, 0x0010, b"\xCC"),
            ":00000001FF",
        ])
        image = parse_intel_hex(text)

        data, filled = image.read(FLASH_BASE, 0x11)
        self.assertEqual(filled, 3)
        self.assertEqual(data[:2], b"\xAA\xBB")
        self.assertEqual(data[2:16], bytes(14))
        self.assertEqual(data[16], 0xCC)


class TestDeviceImageCheck(unittest.TestCase):
    def test_the_devices_own_image_passes(self):
        check_device_image(parse_intel_hex(device_hex(b"\x00" * 100)))

    def test_an_image_for_the_smaller_board_is_refused(self):
        image = parse_intel_hex(device_hex(flash_size=0x00200000))

        with self.assertRaises(FirmwareImageError) as caught:
            check_device_image(image)
        self.assertIn("2 MB", str(caught.exception))

    def test_an_image_that_does_not_start_at_the_flash_is_refused(self):
        image = parse_intel_hex(device_hex(base=0x00000000))

        with self.assertRaises(FirmwareImageError):
            check_device_image(image)

    def test_an_image_without_the_flash_configuration_is_refused(self):
        text = "\n".join([
            hex_record(0x04, 0, b"\x60\x00"),
            hex_record(0x00, 0, b"\x00" * 16),
            ":00000001FF",
        ])
        with self.assertRaises(FirmwareImageError):
            check_device_image(parse_intel_hex(text))


class TestReports(unittest.TestCase):
    def test_a_block_report_carries_the_flash_offset_and_the_block(self):
        report = block_report(FLASH_BASE + 3 * BLOCK_SIZE, b"\xDE\xAD")

        self.assertEqual(len(report), REPORT_SIZE)
        self.assertEqual(report[0], 0)
        self.assertEqual(report[1:4], (3 * BLOCK_SIZE).to_bytes(3, "little"))
        self.assertEqual(report[4:65], bytes(61))
        self.assertEqual(report[65:67], b"\xDE\xAD")
        self.assertEqual(report[67:], bytes(BLOCK_SIZE - 2))

    def test_the_reboot_report_addresses_past_the_flash(self):
        self.assertEqual(reboot_report()[1:4], b"\xFF\xFF\xFF")

    def test_blocks_the_file_has_nothing_for_are_skipped_but_never_the_first(self):
        text = "\n".join([
            hex_record(0x04, 0, b"\x60\x00"),
            hex_record(0x00, 0x0000, b"\x11"),
            hex_record(0x04, 0, b"\x60\x00"),
            hex_record(0x00, 0x0C00, b"\x22"),   # block 3
            ":00000001FF",
        ])
        blocks = plan_blocks(parse_intel_hex(text))

        self.assertEqual([address - FLASH_BASE for address, _ in blocks], [0, 3 * BLOCK_SIZE])


class FakeBootloader:
    """Refuses the first ``busy`` writes of every report, as the real one
    does while it is still working on the last block."""

    def __init__(self, busy=2):
        self.busy = busy
        self._refusals = 0
        self.reports = []
        self.closed = False

    def write(self, report):
        if self._refusals < self.busy:
            self._refusals += 1
            raise OSError("stall")
        self._refusals = 0
        self.reports.append(bytes(report))

    def close(self):
        self.closed = True


class FakeBus:
    """What is on the bus: nothing, the bootloader, or the running port."""

    def __init__(self):
        self.bootloader = None
        self.port = "COM9"
        self.restart_requests = []
        self.device = FakeBootloader()

    def request_bootloader(self, port):
        self.restart_requests.append(port)
        self.port = None
        self.bootloader = BootloaderDevice("fake")

    def find_bootloader(self):
        return self.bootloader

    def open_bootloader(self, device):
        return self.device

    def find_running_port(self):
        return self.port


class TestUpdater(unittest.TestCase):
    def make(self, bus):
        self.steps = []
        self.progress = []
        updater = FirmwareUpdater(
            status=self.steps.append,
            progress=lambda done, total: self.progress.append((done, total)),
            sleep=lambda seconds: None,
            clock=Clock(),
        )
        updater.find_bootloader = bus.find_bootloader
        updater.open_bootloader = bus.open_bootloader
        updater.request_bootloader = bus.request_bootloader
        updater.find_running_port = bus.find_running_port
        return updater

    def test_a_running_device_is_restarted_written_and_rebooted(self):
        bus = FakeBus()
        image = parse_intel_hex(device_hex(b"\x5A" * 1500))
        updater = self.make(bus)

        # The device comes back once the reboot report has been taken.
        original_write = bus.device.write

        def write(report):
            original_write(report)
            if report[1:4] == b"\xFF\xFF\xFF":
                bus.port = "COM9"

        bus.device.write = write

        port = updater.run(image, "COM9")

        self.assertEqual(port, "COM9")
        self.assertEqual(bus.restart_requests, ["COM9"])
        self.assertEqual(
            self.steps, ["restarting", "waiting", "uploading", "rebooting", "returning"]
        )
        # 512 + 1500 bytes span two blocks, then the reboot.
        addresses = [r[1:4] for r in bus.device.reports]
        self.assertEqual(addresses, [b"\x00\x00\x00", b"\x00\x04\x00", b"\xFF\xFF\xFF"])
        self.assertEqual(self.progress[0][0], 0)
        self.assertEqual(self.progress[-1][0], self.progress[-1][1])
        self.assertTrue(bus.device.closed)

    def test_a_device_already_in_update_mode_is_written_without_a_restart(self):
        bus = FakeBus()
        bus.bootloader = BootloaderDevice("fake")
        updater = self.make(bus)

        updater.run(parse_intel_hex(device_hex()), None)

        self.assertEqual(bus.restart_requests, [])
        self.assertEqual(self.steps, ["uploading", "rebooting", "returning"])

    def test_a_bootloader_that_never_appears_is_reported(self):
        bus = FakeBus()
        bus.request_bootloader = lambda port: bus.restart_requests.append(port)
        updater = self.make(bus)

        with self.assertRaises(FirmwareUpdateError) as caught:
            updater.run(parse_intel_hex(device_hex()), "COM9")
        self.assertEqual(caught.exception.kind, "no_bootloader")

    def test_a_write_the_bootloader_keeps_refusing_fails_the_update(self):
        bus = FakeBus()
        bus.bootloader = BootloaderDevice("fake")
        bus.device = FakeBootloader(busy=10_000)
        updater = self.make(bus)

        with self.assertRaises(FirmwareUpdateError) as caught:
            updater.run(parse_intel_hex(device_hex()), None)
        self.assertEqual(caught.exception.kind, "write")
        self.assertTrue(bus.device.closed)

    def test_a_reboot_report_the_device_never_takes_is_not_a_failure(self):
        """The device is gone the moment it takes the reboot command, so
        the last try can only be refused. What counts is it coming back."""
        bus = FakeBus()
        bus.bootloader = BootloaderDevice("fake")
        device = FakeBootloader(busy=0)
        original_write = device.write

        def write(report):
            if report[1:4] == b"\xFF\xFF\xFF":
                raise OSError("gone")
            original_write(report)

        device.write = write
        bus.device = device
        updater = self.make(bus)

        self.assertEqual(updater.run(parse_intel_hex(device_hex()), None), "COM9")

    def test_a_device_that_does_not_come_back_is_reported(self):
        bus = FakeBus()
        bus.bootloader = BootloaderDevice("fake")
        bus.port = None
        updater = self.make(bus)

        with self.assertRaises(FirmwareUpdateError) as caught:
            updater.run(parse_intel_hex(device_hex()), None)
        self.assertEqual(caught.exception.kind, "not_back")


class Clock:
    """Monotonic time that moves a lot per read, so waits expire."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


if __name__ == "__main__":
    unittest.main()
