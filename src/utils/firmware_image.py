"""A device firmware image, read from an Intel HEX file and checked.

The device's firmware ships as an Intel HEX file whose records address the
flash directly, so the file says where every byte goes. What this module
adds is the checking: that the file is a firmware image at all, that it is
one for this device and not for a smaller relative of it, and that it fits.
Refusing a wrong file here costs nothing; writing one would leave a device
that does not start.
"""
from dataclasses import dataclass, field

#: Where the device's flash begins, and where its firmware image starts.
FLASH_BASE = 0x60000000
#: The end of what the update path may write. The last 256 KB of the 8 MB
#: flash are the device's own, for its settings and the bootloader's use.
FLASH_LIMIT = 0x607C0000
#: The first eight bytes of a valid image: the flash configuration block's
#: "FCFB" tag and version, little-endian.
_FLASH_CONFIG_TAG = 0x5601000042464346
#: Offset of the flash size inside the configuration block, and the size
#: this device has. A file built for the 2 MB variant carries 0x00200000
#: here and must not be written.
_FLASH_SIZE_OFFSET = 80
DEVICE_FLASH_SIZE = 0x00800000


class FirmwareImageError(ValueError):
    """The file is not a firmware image this device can take."""


@dataclass
class FirmwareImage:
    """Bytes at absolute addresses, in as many runs as the file had."""

    segments: dict = field(default_factory=dict)   # start address -> bytearray

    @property
    def min_address(self):
        return min(self.segments) if self.segments else 0

    @property
    def max_address(self):
        """One past the last byte."""
        if not self.segments:
            return 0
        return max(start + len(data) for start, data in self.segments.items())

    @property
    def total_size(self):
        return sum(len(data) for data in self.segments.values())

    def read(self, address, size):
        """The bytes in [address, address + size), zero where the file has
        none, and how many of them the file supplied."""
        out = bytearray(size)
        filled = 0
        for start, data in self.segments.items():
            end = start + len(data)
            lo = max(address, start)
            hi = min(address + size, end)
            if lo < hi:
                out[lo - address:hi - address] = data[lo - start:hi - start]
                filled += hi - lo
        return bytes(out), filled

    def _add(self, address, data):
        for start, existing in self.segments.items():
            if start + len(existing) == address:
                existing.extend(data)
                return
        self.segments[address] = bytearray(data)


def parse_intel_hex(text):
    """Read Intel HEX records into a FirmwareImage.

    Understands data (00), end of file (01), extended segment address
    (02) and extended linear address (04) records; the start address
    records (03, 05) carry nothing the flash needs and are skipped. A
    record whose checksum or length does not add up fails the whole file:
    a corrupted download is the one thing this must not write.
    """
    image = FirmwareImage()
    upper = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise FirmwareImageError(f"line {number}: not an Intel HEX record")
        try:
            record = bytes.fromhex(line[1:])
        except ValueError:
            raise FirmwareImageError(f"line {number}: not hexadecimal") from None
        if len(record) < 5:
            raise FirmwareImageError(f"line {number}: record too short")
        length, offset, rtype = record[0], int.from_bytes(record[1:3], "big"), record[3]
        if len(record) != length + 5:
            raise FirmwareImageError(f"line {number}: length does not match")
        if sum(record) & 0xFF:
            raise FirmwareImageError(f"line {number}: checksum mismatch")
        data = record[4:4 + length]
        if rtype == 0x00:
            image._add(upper + offset, data)
        elif rtype == 0x01:
            break
        elif rtype == 0x02:
            upper = int.from_bytes(data, "big") << 4
        elif rtype == 0x04:
            upper = int.from_bytes(data, "big") << 16
        elif rtype in (0x03, 0x05):
            continue
        else:
            raise FirmwareImageError(f"line {number}: unknown record type {rtype:#04x}")
    if not image.segments:
        raise FirmwareImageError("the file holds no data")
    return image


def check_device_image(image):
    """Raise FirmwareImageError unless the image is one this device runs.

    The flash configuration block at the start of the flash is what the
    chip boots from, so a real image always begins there, with its tag,
    and names the flash it was built for. Anything else is either not a
    firmware image or was built for another board.
    """
    if image.min_address != FLASH_BASE:
        raise FirmwareImageError("the image does not start at the device's flash")
    head, filled = image.read(FLASH_BASE, _FLASH_SIZE_OFFSET + 4)
    if filled < _FLASH_SIZE_OFFSET + 4:
        raise FirmwareImageError("the image is missing its flash configuration")
    if int.from_bytes(head[:8], "little") != _FLASH_CONFIG_TAG:
        raise FirmwareImageError("the image has no flash configuration block")
    flash_size = int.from_bytes(head[_FLASH_SIZE_OFFSET:_FLASH_SIZE_OFFSET + 4], "little")
    if flash_size != DEVICE_FLASH_SIZE:
        raise FirmwareImageError(
            f"the image was built for a {flash_size // 1048576} MB flash, "
            f"not this device's {DEVICE_FLASH_SIZE // 1048576} MB"
        )
    if image.max_address > FLASH_LIMIT:
        raise FirmwareImageError("the image is too large for the device")


def load_device_image(path):
    """Read and check a firmware file. Raises FirmwareImageError."""
    try:
        with open(path, "r", encoding="ascii", errors="strict") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as e:
        raise FirmwareImageError(f"could not read the file: {e}") from e
    image = parse_intel_hex(text)
    check_device_image(image)
    return image
