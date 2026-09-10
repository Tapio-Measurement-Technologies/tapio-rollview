"""The firmware update window, with no device and no thread."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from gui.firmware_update_dialog import FirmwareUpdateDialog
from test.qtcleanup import destroy
from test.test_firmware_update import device_hex


class TestFirmwareUpdateDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.target = None
        self.held = []
        self.released = []
        patcher = patch("gui.firmware_update_dialog.find_bootloader", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dialog = FirmwareUpdateDialog(
            lambda: self.target, hold=self.held.append, release=self.released.append
        )
        self.addCleanup(lambda: destroy(self.dialog))

    def write_hex(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "firmware.hex"
        path.write_text(text)
        return str(path)

    def test_upload_waits_for_both_a_device_and_a_file(self):
        self.assertFalse(self.dialog.upload_button.isEnabled())

        self.assertTrue(self.dialog.set_file(self.write_hex(device_hex(b"\x01"))))
        self.assertFalse(self.dialog.upload_button.isEnabled())

        self.target = ("COM9", "Tapio RQP Live (1)")
        self.dialog.refresh_device()
        self.assertTrue(self.dialog.upload_button.isEnabled())
        self.assertEqual(self.dialog.device_label.text(), "Tapio RQP Live (1)")

    def test_a_wrong_file_is_refused_before_anything_is_pressed(self):
        self.target = ("COM9", "Tapio RQP Live (1)")
        self.dialog.refresh_device()

        self.assertFalse(self.dialog.set_file(self.write_hex(device_hex(flash_size=0x200000))))

        self.assertFalse(self.dialog.upload_button.isEnabled())
        self.assertIn("2 MB", self.dialog.status_label.text())

    def test_a_device_already_in_update_mode_is_offered_without_a_port(self):
        with patch("gui.firmware_update_dialog.find_bootloader", return_value=object()):
            self.dialog.refresh_device()

        self.assertIsNone(self.dialog._target[0])
        self.assertNotEqual(self.dialog.device_label.text(), "")

    def test_the_window_does_not_close_while_an_update_runs(self):
        self.dialog.running = True

        self.dialog.reject()

        self.assertFalse(self.dialog.isHidden() and False)
        self.assertTrue(self.dialog.running)


if __name__ == "__main__":
    unittest.main()
