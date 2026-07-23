import json
import tempfile
import unittest
from pathlib import Path

from utils.sync_history import SyncHistory


class TestSyncHistory(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="rqft-test-history-")
        self.addCleanup(self.root.cleanup)

    def make(self, device_key="RQP-123"):
        return SyncHistory(device_key, self.root.name)

    def test_round_trip(self):
        history = self.make()
        history.load()
        history.record("roll/a.prof", 100, 0xDEADBEEF)
        history.save()

        reloaded = self.make()
        reloaded.load()
        self.assertTrue(reloaded.known("roll/a.prof", 0xDEADBEEF))
        self.assertFalse(reloaded.known("roll/b.prof", 0xDEADBEEF))

    def test_missing_file_loads_empty(self):
        history = self.make()
        history.load()
        self.assertFalse(history.known("roll/a.prof", 1))

    def test_corrupt_file_loads_empty(self):
        history = self.make()
        Path(history.path).parent.mkdir(parents=True)
        Path(history.path).write_text("{not json", encoding="utf-8")
        history.load()
        self.assertFalse(history.known("roll/a.prof", 1))
        # And it can be saved over afterwards.
        history.record("roll/a.prof", 1, 1)
        history.save()
        self.assertEqual(
            json.loads(Path(history.path).read_text(encoding="utf-8"))["version"], 1
        )

    def test_known_compares_crc(self):
        history = self.make()
        history.record("roll/a.prof", 100, 0x1111)
        # Same content: known. Recreated with new content: new file.
        self.assertTrue(history.known("roll/a.prof", 0x1111))
        self.assertFalse(history.known("roll/a.prof", 0x2222))
        # No CRC on either side: the recorded path decides.
        self.assertTrue(history.known("roll/a.prof", None))

    def test_prune_drops_files_gone_from_device(self):
        history = self.make()
        history.record("roll/a.prof", 1, 1)
        history.record("roll/b.prof", 2, 2)
        history.prune(["roll/b.prof"])
        self.assertFalse(history.known("roll/a.prof", 1))
        self.assertTrue(history.known("roll/b.prof", 2))

    def test_device_key_sanitized_for_filename(self):
        history = SyncHistory("RQP/12:3 *", self.root.name)
        history.record("roll/a.prof", 1, 1)
        history.save()
        name = Path(history.path).name
        self.assertTrue(name.endswith(".json"))
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)
        self.assertNotIn(" ", name)
        self.assertNotIn("*", name)

    def test_save_leaves_no_temp_file(self):
        history = self.make()
        history.record("roll/a.prof", 1, 1)
        history.save()
        directory = Path(history.path).parent
        self.assertEqual(
            [p.name for p in directory.iterdir()], [Path(history.path).name]
        )


if __name__ == "__main__":
    unittest.main()
