import unittest

import settings
from utils.rqft_support import (
    firmware_supports_rqft,
    is_syncable_prof,
    parse_firmware_version,
)


class TestParseFirmwareVersion(unittest.TestCase):
    def test_plain_semver(self):
        self.assertEqual(parse_firmware_version("1.2.0"), (1, 2, 0))

    def test_v_prefixed_semver(self):
        self.assertEqual(parse_firmware_version("v1.2.0"), (1, 2, 0))

    def test_git_describe_suffix(self):
        self.assertEqual(parse_firmware_version("v1.2.0-5-gabc123"), (1, 2, 0))

    def test_dirty_suffix(self):
        self.assertEqual(parse_firmware_version("v1.2.0-d"), (1, 2, 0))

    def test_bare_commit_hash_returns_none(self):
        self.assertIsNone(parse_firmware_version("404043e"))

    def test_dirty_commit_hash_returns_none(self):
        # "404043e-d" starts with digits but is not a semver
        self.assertIsNone(parse_firmware_version("abc123f-d"))

    def test_empty_and_garbage(self):
        self.assertIsNone(parse_firmware_version(""))
        self.assertIsNone(parse_firmware_version("unknown"))
        self.assertIsNone(parse_firmware_version(None))


class TestFirmwareSupportsRqft(unittest.TestCase):
    def setUp(self):
        self.original_force_rqft = settings.FORCE_RQFT
        self.original_min_version = settings.RQFT_MIN_FIRMWARE_VERSION
        settings.FORCE_RQFT = False
        settings.RQFT_MIN_FIRMWARE_VERSION = (1, 2, 0)

    def tearDown(self):
        settings.FORCE_RQFT = self.original_force_rqft
        settings.RQFT_MIN_FIRMWARE_VERSION = self.original_min_version

    def test_version_at_gate_supports(self):
        self.assertTrue(firmware_supports_rqft("v1.2.0"))

    def test_version_above_gate_supports(self):
        self.assertTrue(firmware_supports_rqft("v2.0.1"))
        self.assertTrue(firmware_supports_rqft("v1.10.0"))

    def test_older_version_does_not_support(self):
        self.assertFalse(firmware_supports_rqft("v1.1.4"))
        self.assertFalse(firmware_supports_rqft("v1.1.4-67-g404043e"))

    def test_unparseable_version_does_not_support(self):
        self.assertFalse(firmware_supports_rqft("404043e"))
        self.assertFalse(firmware_supports_rqft(""))

    def test_force_flag_bypasses_gate(self):
        settings.FORCE_RQFT = True
        self.assertTrue(firmware_supports_rqft("404043e"))
        self.assertTrue(firmware_supports_rqft("v1.1.4"))
        self.assertTrue(firmware_supports_rqft(""))


class TestIsSyncableProf(unittest.TestCase):
    def test_prof_file_is_syncable(self):
        self.assertTrue(is_syncable_prof("250520-134139/measurement.prof"))
        self.assertTrue(is_syncable_prof("a.prof"))

    def test_mean_prof_is_not_syncable(self):
        self.assertFalse(is_syncable_prof("250520-134139/mean.prof"))
        self.assertFalse(is_syncable_prof("mean.prof"))

    def test_other_files_are_not_syncable(self):
        self.assertFalse(is_syncable_prof("readme.txt"))
        self.assertFalse(is_syncable_prof("logs/boot.log"))
        self.assertFalse(is_syncable_prof("250520-134139/export.profx"))


if __name__ == "__main__":
    unittest.main()
