import datetime
import os
import time
import unittest
from unittest.mock import patch

from utils.time_sync import device_wall_clock_to_epoch, get_timestamp


class TimeZoneFixture(unittest.TestCase):
    """Pins TZ for the duration of a test, since both halves of the device
    clock convention read the local zone."""

    def use_timezone(self, tz):
        previous = os.environ.get("TZ")
        os.environ["TZ"] = tz
        time.tzset()

        def restore():
            if previous is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = previous
            time.tzset()

        self.addCleanup(restore)


class TestDeviceClockRoundTrip(TimeZoneFixture):
    def test_a_synced_clock_reads_back_as_the_time_it_was_set_to(self):
        # The bug this covers: the device reports local wall-clock fields
        # packed as an epoch, so using them directly put every synced file a
        # whole UTC offset into the future.
        for tz in ("Europe/Helsinki", "America/New_York", "UTC"):
            with self.subTest(tz=tz):
                self.use_timezone(tz)
                before = time.time()
                recovered = device_wall_clock_to_epoch(get_timestamp())
                self.assertAlmostEqual(recovered, before, delta=2)

    def test_a_negative_utc_offset_is_not_flipped_positive(self):
        # timedelta.seconds normalises to a positive field, so reading it
        # instead of total_seconds() sent western zones hours into the future.
        self.use_timezone("America/New_York")
        offset = datetime.datetime.now().astimezone().utcoffset()
        self.assertLess(offset.total_seconds(), 0)
        self.assertGreater(get_timestamp(), 0)
        self.assertAlmostEqual(
            get_timestamp() - time.time(), offset.total_seconds(), delta=2
        )

    def test_a_file_written_under_the_other_dst_offset_keeps_its_wall_clock(self):
        self.use_timezone("Europe/Helsinki")
        # A file written at 12:00 in January (EET, +2) read back in August.
        winter_wall_clock = datetime.datetime(2026, 1, 15, 12, 0, 0)
        reported = winter_wall_clock.replace(
            tzinfo=datetime.timezone.utc
        ).timestamp()

        recovered = datetime.datetime.fromtimestamp(
            device_wall_clock_to_epoch(reported)
        )
        self.assertEqual(recovered.replace(tzinfo=None), winter_wall_clock)


if __name__ == "__main__":
    unittest.main()
