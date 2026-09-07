"""Every serial failure sorted into a cause, and each cause worded once."""

import errno
import unittest

import serial

from utils.serial_errors import (
    CAUSE_GONE,
    CAUSE_HELD,
    CAUSE_LINK_LOST,
    CAUSE_SILENT,
    CAUSE_UNKNOWN,
    CAUSE_UNREACHABLE,
    CAUSES,
    classify_port_error,
    describe_port_error,
)

# pyserial's own wording on Windows, verbatim from this machine.
WIN_HELD = "could not open port 'COM6': PermissionError(13, 'Access is denied.', None, 5)"
WIN_OFF = "could not open port 'COM10': OSError(22, 'The semaphore timeout period has expired.', None, 121)"
WIN_GONE = "could not open port 'COM99': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)"
WIN_READ_FAILED = "ClearCommError failed (PermissionError(13, 'The device does not recognize the command.', None, 22))"
WIN_WRITE_FAILED = "WriteFile failed (OSError(22, 'A device attached to the system is not functioning.', None, 31))"
# The same codes with the operating system's text in another language.
WIN_HELD_LOCALISED = "could not open port 'COM6': PermissionError(13, 'Käyttö estetty.', None, 5)"
# pyserial's wording on POSIX.
POSIX_GONE = "[Errno 2] could not open port /dev/ttyUSB0: [Errno 2] No such file or directory: '/dev/ttyUSB0'"
POSIX_HELD = "[Errno 16] could not open port /dev/rfcomm0: [Errno 16] Device or resource busy: '/dev/rfcomm0'"
POSIX_OFF = "[Errno 112] could not open port /dev/rfcomm0: [Errno 112] Host is down"


class TestClassification(unittest.TestCase):
    def test_windows_open_failures_by_code(self):
        self.assertEqual(classify_port_error(serial.SerialException(WIN_HELD)), CAUSE_HELD)
        self.assertEqual(classify_port_error(serial.SerialException(WIN_OFF)), CAUSE_UNREACHABLE)
        self.assertEqual(classify_port_error(serial.SerialException(WIN_GONE)), CAUSE_GONE)

    def test_the_code_decides_whatever_language_windows_speaks(self):
        self.assertEqual(classify_port_error(WIN_HELD_LOCALISED), CAUSE_HELD)

    def test_windows_failures_after_the_open_are_a_lost_link(self):
        self.assertEqual(classify_port_error(serial.SerialException(WIN_READ_FAILED), opened=True), CAUSE_LINK_LOST)
        self.assertEqual(classify_port_error(serial.SerialException(WIN_WRITE_FAILED), opened=True), CAUSE_LINK_LOST)
        # Access denied on a port that had opened is the link going, not
        # another program.
        self.assertEqual(classify_port_error(WIN_HELD, opened=True), CAUSE_LINK_LOST)

    def test_posix_failures_by_errno_in_the_text(self):
        self.assertEqual(classify_port_error(POSIX_GONE), CAUSE_GONE)
        self.assertEqual(classify_port_error(POSIX_HELD), CAUSE_HELD)
        self.assertEqual(classify_port_error(POSIX_OFF), CAUSE_UNREACHABLE)

    def test_posix_failures_by_errno_on_the_exception(self):
        self.assertEqual(classify_port_error(OSError(errno.EBUSY, "busy")), CAUSE_HELD)
        self.assertEqual(classify_port_error(OSError(errno.ENOENT, "missing")), CAUSE_GONE)
        self.assertEqual(classify_port_error(OSError(errno.EIO, "io"), opened=True), CAUSE_LINK_LOST)

    def test_a_chained_cause_is_read_through(self):
        try:
            try:
                raise OSError(errno.EBUSY, "busy")
            except OSError as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as wrapped:
            self.assertEqual(classify_port_error(wrapped), CAUSE_HELD)

    def test_words_are_the_fallback_when_there_is_no_code(self):
        self.assertEqual(classify_port_error("Access is denied"), CAUSE_HELD)
        self.assertEqual(classify_port_error("read timed out"), CAUSE_UNREACHABLE)
        self.assertEqual(classify_port_error("no such file"), CAUSE_GONE)

    def test_nothing_recognisable_is_unknown_before_the_open_and_lost_after(self):
        self.assertEqual(classify_port_error(RuntimeError("gone")), CAUSE_UNKNOWN)
        self.assertEqual(classify_port_error(serial.SerialTimeoutException("Write timeout"), opened=True), CAUSE_LINK_LOST)

    def test_no_error_at_all_means_the_device_was_silent(self):
        self.assertEqual(classify_port_error(None), CAUSE_SILENT)

    def test_a_cause_passes_through(self):
        for cause in CAUSES:
            self.assertEqual(classify_port_error(cause), cause)


class TestWording(unittest.TestCase):
    def test_every_cause_has_a_title_a_sentence_and_a_hint(self):
        seen = set()
        for cause in CAUSES:
            text = describe_port_error(cause, "COM6", "Tapio RQP Live (1)")
            self.assertEqual(text.cause, cause)
            self.assertTrue(text.title and text.sentence and text.hint, cause)
            self.assertNotIn("PORT_ERROR", text.body, "an untranslated key leaked")
            self.assertIn("COM6", text.body)
            seen.add(text.title)
        self.assertEqual(len(seen), len(CAUSES), "titles must tell the causes apart")

    def test_the_unit_is_named_when_known_and_called_the_device_otherwise(self):
        named = describe_port_error(WIN_OFF, "COM10", "Tapio RQP Live (2748487262)")
        self.assertIn("Tapio RQP Live (2748487262)", named.sentence)
        anonymous = describe_port_error(WIN_OFF, "COM10")
        self.assertIn("The device", anonymous.sentence)

    def test_the_hint_says_connect_not_plug_in(self):
        for cause in CAUSES:
            self.assertNotIn("plug", describe_port_error(cause, "COM1").hint.casefold())

    def test_held_is_worded_as_another_program(self):
        self.assertIn("another program", describe_port_error(WIN_HELD, "COM6").body)


if __name__ == "__main__":
    unittest.main()
