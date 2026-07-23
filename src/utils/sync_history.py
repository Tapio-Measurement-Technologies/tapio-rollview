"""
Per-device record of files already pulled over RQFT.

An incremental sync (requested by the device's NOTIFY with the
SYNC_INCREMENTAL sync-mode flag) skips every remote file recorded here
even when the local copy is gone, so files the user deleted from the
mirror stay deleted. A full sync ignores the record for planning but
rebuilds it from what it fetches and skips.

One JSON file per device lives under ``<mirror root>/.sync_history/``, so
wiping the mirror folder also resets the history and the next sync pulls
everything again. The device key is the device serial number when known,
otherwise the port name (histories then split per port, which is harmless).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_HISTORY_DIR_NAME = ".sync_history"
_FORMAT_VERSION = 1


def _sanitize(device_key: str) -> str:
    """Reduce a device key to a safe filename component."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", device_key) or "device"


class SyncHistory:
    """Load, query, and atomically persist one device's synced-file record."""

    def __init__(self, device_key: str, root_dir: str):
        self._device_key = device_key
        self._path = os.path.join(
            root_dir, _HISTORY_DIR_NAME, f"{_sanitize(device_key)}.json"
        )
        self._files: dict[str, dict] = {}

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> None:
        """Read the record; a missing or corrupt file yields an empty one."""
        self._files = {}
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            files = data.get("files", {})
            if isinstance(files, dict):
                self._files = {
                    path: entry
                    for path, entry in files.items()
                    if isinstance(entry, dict)
                }
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning(f"Sync history {self._path} unreadable, starting empty: {e}")

    def known(self, path: str, remote_crc: int | None) -> bool:
        """Whether this remote file was already synced with the same content.

        A file re-created on the device with different content counts as
        new, so it is pulled even by an incremental sync. When either side
        lacks a CRC the recorded path alone decides.
        """
        entry = self._files.get(path)
        if entry is None:
            return False
        recorded_crc = entry.get("crc32")
        if remote_crc is None or recorded_crc is None:
            return True
        return recorded_crc == remote_crc

    def record(self, path: str, size: int, crc32: int | None) -> None:
        self._files[path] = {
            "size": size,
            "crc32": crc32,
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def prune(self, current_remote_paths) -> None:
        """Drop entries for files no longer present on the device."""
        keep = set(current_remote_paths)
        self._files = {
            path: entry for path, entry in self._files.items() if path in keep
        }

    def save(self) -> None:
        """Atomically write the record; failures log and never raise."""
        data = {
            "version": _FORMAT_VERSION,
            "device_key": self._device_key,
            "files": self._files,
        }
        tmp_path = f"{self._path}.tmp"
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self._path)
        except OSError as e:
            log.warning(f"Sync history {self._path} not saved: {e}")
