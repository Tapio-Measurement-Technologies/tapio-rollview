"""What a crash looks like before there is an interface to show it in.

An unhandled exception normally lands in the crash dialog. Startup exceptions
do not get that far: until ``main()`` has built the QApplication there is no
application for a dialog to belong to, and constructing one anyway is fatal to
Qt -- it aborts with "Must construct a QApplication before a QWidget", which is
then the only thing anyone sees of the original failure.
"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class _Recorder:
    """The console, as far as the crash reporter is concerned."""

    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text

    def flush(self):
        pass


class TestCrashBeforeTheApplicationExists(unittest.TestCase):
    def _manager(self):
        from utils.logging import LogManager

        return LogManager(MagicMock(), MagicMock())

    def test_the_traceback_is_printed_instead_of_shown(self):
        console = _Recorder()
        manager = self._manager()

        with patch("PySide6.QtWidgets.QApplication.instance", return_value=None), \
             patch("gui.crash_dialog.CrashDialog") as dialog, \
             patch.object(sys, "stderr", SimpleNamespace(original_stream=console)):
            with self.assertRaises(SystemExit) as exit_status:
                manager.handle_crash("Traceback: the real error\n")

        self.assertIn("the real error", console.text)
        dialog.assert_not_called()
        self.assertEqual(exit_status.exception.code, 1)

    def test_a_windowed_build_with_no_console_reports_nothing_and_exits(self):
        manager = self._manager()

        with patch("PySide6.QtWidgets.QApplication.instance", return_value=None), \
             patch("gui.crash_dialog.CrashDialog") as dialog, \
             patch.object(sys, "stderr", SimpleNamespace(original_stream=None)), \
             patch.object(sys, "__stderr__", None):
            with self.assertRaises(SystemExit):
                manager.handle_crash("Traceback: the real error\n")

        dialog.assert_not_called()

    def test_the_dialog_is_still_used_once_there_is_an_application(self):
        manager = self._manager()

        with patch("PySide6.QtWidgets.QApplication.instance", return_value=MagicMock()), \
             patch("utils.logging.CrashDialog") as dialog:
            with self.assertRaises(SystemExit):
                manager.handle_crash("Traceback: the real error\n")

        dialog.assert_called_once()
        dialog.return_value.exec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
