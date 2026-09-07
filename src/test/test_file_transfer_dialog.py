"""The window a sync reports in.

It exists because the status bar could not hold what a sync has to say:
one line of fixed height, shared with the guidance, for a file name, two
counts and two bars whose text changes length as it changes value.
"""

import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from gui.file_transfer_dialog import FileTransferDialog


class DialogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = MagicMock()
        self.dialog = FileTransferDialog(self.manager)
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.hide)


class TestProgress(DialogCase):
    def test_the_wait_before_the_device_answers_is_uncounted(self):
        """A device that is switched off answers exactly as fast as one
        that is thinking, so until a count arrives there is nothing to
        count and the bar says only that something is happening."""
        self.dialog.begin("Tapio RQP Live (1)")

        self.assertEqual(self.dialog.total_progress_bar.maximum(), 0)
        self.assertIn("Tapio RQP Live (1)", self.dialog.windowTitle())

        self.dialog.set_batch(12, 4096)

        self.assertEqual(self.dialog.total_progress_bar.maximum(), 100)
        self.assertIn("12", self.dialog.batch_label.text())

    def test_the_total_counts_the_file_in_flight_as_a_fraction(self):
        """A bar that only moved between files would sit still for the
        whole of one large profile."""
        self.dialog.begin()
        self.dialog.set_batch(4, 1024)

        self.dialog.set_current_file(1, 4, "a.prof")
        self.assertEqual(self.dialog.total_progress_bar.value(), 0)
        self.dialog.set_byte_progress(512, 1024)
        self.assertEqual(self.dialog.current_file_progress_bar.value(), 50)
        self.assertEqual(self.dialog.total_progress_bar.value(), 12)

        self.dialog.set_current_file(4, 4, "d.prof")
        self.dialog.set_byte_progress(1024, 1024)
        self.assertEqual(self.dialog.total_progress_bar.value(), 100)

    def test_the_file_in_flight_is_named_with_its_bytes(self):
        self.dialog.begin()
        self.dialog.set_current_file(2, 3, "250520-134139/b.prof")
        self.dialog.set_byte_progress(2048, 8192)

        self.assertEqual(self.dialog.current_file_label.text(), "250520-134139/b.prof")
        self.assertIn("2.00", self.dialog.current_file_byte_label.text())
        self.assertIn("8.00", self.dialog.current_file_byte_label.text())
        self.assertIn("2", self.dialog.status_label.text())
        self.assertIn("3", self.dialog.status_label.text())

    def test_no_file_bar_is_shown_before_a_file_is_arriving(self):
        """An empty bar under a blank name is a measurement of nothing."""
        self.dialog.begin()
        self.assertFalse(self.dialog.current_file_progress_bar.isVisibleTo(self.dialog))

        self.dialog.set_current_file(1, 3, "a.prof")
        self.assertTrue(self.dialog.current_file_progress_bar.isVisibleTo(self.dialog))

    def test_a_second_sync_starts_from_nothing(self):
        self.dialog.begin()
        self.dialog.set_batch(4, 1024)
        self.dialog.set_current_file(3, 4, "c.prof")
        self.dialog.set_byte_progress(512, 1024)
        self.dialog.finish()

        self.dialog.begin("Another unit")

        self.assertEqual(self.dialog.current_file_label.text(), "")
        self.assertEqual(self.dialog.current_file_byte_label.text(), "")
        self.assertEqual(self.dialog.batch_label.text(), "")
        self.assertEqual(self.dialog.current_file_progress_bar.value(), 0)
        self.assertEqual(self.dialog.total_progress_bar.maximum(), 0)


class TestCancel(DialogCase):
    def test_cancel_asks_the_manager_and_says_it_is_cancelling(self):
        self.dialog.begin()

        self.dialog.cancel_button.click()

        self.manager.cancel_transfer.assert_called_once()
        self.assertFalse(self.dialog.cancel_button.isEnabled())
        self.assertNotEqual(self.dialog.cancel_button.text(), "")

    def test_the_window_stays_up_until_the_transfer_actually_ends(self):
        """A Bluetooth read can be seconds from returning; a window that
        vanished on the press would claim the sync had stopped before it
        had."""
        self.dialog.begin()

        self.dialog.cancel()

        self.assertTrue(self.dialog.isVisible())
        self.dialog.finish()
        self.assertFalse(self.dialog.isVisible())

    def test_closing_the_window_stops_the_sync_rather_than_hiding_it(self):
        """This window is the only place a running sync can be seen or
        stopped."""
        self.dialog.begin()

        self.dialog.reject()

        self.manager.cancel_transfer.assert_called_once()
        self.assertTrue(self.dialog.isVisible())

    def test_pressing_cancel_twice_asks_once(self):
        self.dialog.begin()

        self.dialog.cancel()
        self.dialog.cancel()

        self.manager.cancel_transfer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
