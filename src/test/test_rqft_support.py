import unittest

import settings
from utils.rqft_support import (
    firmware_supports_rqft,
    is_syncable_prof,
    parse_firmware_version,
    plan_device_deletes,
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

    def test_pre_release_tags_parse_as_their_release(self):
        # Beta/rc firmware must not fall back to the unparseable path;
        # anything trailing the patch number is ignored on purpose.
        self.assertEqual(parse_firmware_version("v1.2.0-beta"), (1, 2, 0))
        self.assertEqual(parse_firmware_version("1.2.0-beta"), (1, 2, 0))
        self.assertEqual(parse_firmware_version("v1.2.0-rc1"), (1, 2, 0))
        self.assertEqual(parse_firmware_version("v1.2.0-beta.2"), (1, 2, 0))
        self.assertEqual(parse_firmware_version("v1.2.0+build5"), (1, 2, 0))

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

    def test_pre_release_of_the_gate_version_supports(self):
        self.assertTrue(firmware_supports_rqft("v1.2.0-beta"))
        self.assertTrue(firmware_supports_rqft("v1.2.0-rc1"))

    def test_pre_release_below_the_gate_does_not_support(self):
        self.assertFalse(firmware_supports_rqft("v1.1.9-beta"))

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


class TestPlanDeviceDeletes(unittest.TestCase):
    def test_a_fully_verified_folder_goes_as_a_unit(self):
        folders, files = plan_device_deletes(
            ["250520-134139/a.prof", "250520-134139/b.prof"], []
        )
        self.assertEqual(folders, ["250520-134139"])
        self.assertEqual(files, [])

    def test_a_folder_holding_something_unverified_is_deleted_file_by_file(self):
        """Removing the folder would take the file this sync could not
        verify with it."""
        folders, files = plan_device_deletes(
            ["roll/a.prof"], ["roll/b.prof"]
        )
        self.assertEqual(folders, [])
        self.assertEqual(files, ["roll/a.prof"])

    def test_root_level_files_are_never_folded_into_a_folder(self):
        folders, files = plan_device_deletes(["a.prof"], [])
        self.assertEqual(folders, [])
        self.assertEqual(files, ["a.prof"])

    def test_a_folder_is_listed_once_however_many_files_it_holds(self):
        folders, files = plan_device_deletes(
            ["roll/a.prof", "roll/b.prof", "roll/c.prof"], []
        )
        self.assertEqual(folders, ["roll"])
        self.assertEqual(files, [])

    def test_one_incomplete_folder_does_not_spare_the_others(self):
        folders, files = plan_device_deletes(
            ["good/a.prof", "bad/a.prof"], ["bad/b.prof"]
        )
        self.assertEqual(folders, ["good"])
        self.assertEqual(files, ["bad/a.prof"])

    def test_nothing_verified_deletes_nothing(self):
        self.assertEqual(plan_device_deletes([], ["roll/a.prof"]), ([], []))


if __name__ == "__main__":
    unittest.main()
