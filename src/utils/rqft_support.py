"""
RQFT capability policy: which devices get a persistent RQFT connection
and which files the sync pulls from the device's transparent listing.
"""
import re
from dataclasses import dataclass

import settings

_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class DeviceIdentity:
    """Identity a device reported over RQP+DEVICEINFO?."""
    device_name: str
    serial_number: str
    firmware_version: str


@dataclass(frozen=True)
class BusyPortStatus:
    """Cached identity and live-session state for a worker-held port."""
    identity: DeviceIdentity
    connected: bool


def parse_firmware_version(text):
    """
    Parse a git-describe style firmware version into a (major, minor, patch)
    tuple. Accepts "v1.2.0", "1.2.0", "v1.2.0-5-gabc123" and the "-d" dirty
    suffix. Bare commit hashes and unknown strings return None.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def firmware_supports_rqft(firmware_version):
    """
    Whether a device with this firmware version gets a persistent RQFT
    connection. The --force-rqft CLI flag (dev runs only, ignored when
    frozen) bypasses the version gate for device firmware dev builds,
    whose git-describe output is a bare commit hash.
    """
    if settings.FORCE_RQFT:
        return True
    version = parse_firmware_version(firmware_version)
    if version is None:
        return False
    return version >= settings.RQFT_MIN_FIRMWARE_VERSION


def is_syncable_prof(path: str) -> bool:
    """
    Sync policy over the device's transparent file listing: measurement
    .prof files only, excluding device-side mean.prof (rollview computes
    its own).
    """
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".prof") and name != "mean.prof"
