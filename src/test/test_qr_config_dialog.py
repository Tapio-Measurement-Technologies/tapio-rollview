import copy
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from gui.qr_config_dialog import QR_CODE_SIZE_PX, QRConfigDialog
from utils import preferences


class TestQRConfigDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_alert_limits = copy.deepcopy(preferences.alert_limits)
        preferences.alert_limits = [
            {"name": "mean_g", "units": "g", "min": 1.0, "max": 2.0},
            {"name": "stdev_g", "units": "g", "min": None, "max": 3.5},
            {"name": "cv_pct", "units": "%", "min": 4.0, "max": None},
            {"name": "min_g", "units": "g", "min": -1.0, "max": 0.0},
            {"name": "max_g", "units": "g", "min": 5.0, "max": 6.0},
            {"name": "pp_g", "units": "g", "min": None, "max": None},
        ]

    def tearDown(self):
        preferences.alert_limits = self.original_alert_limits
        for widget in QApplication.topLevelWidgets():
            widget.close()

    def test_generate_qr_code_converts_pillow_image_to_scaled_pixmap(self):
        dialog = QRConfigDialog()
        self.addCleanup(dialog.close)

        pixmap = dialog.qr_label.pixmap()

        self.assertIsNotNone(pixmap)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), QR_CODE_SIZE_PX)
        self.assertEqual(pixmap.height(), QR_CODE_SIZE_PX)
        self.assertIn("mean_g_min=1.0", dialog.generate_config_string())
        self.assertIn("cv_prcnt_max=NaN", dialog.generate_config_string())
        self.assertIn("1.0", dialog.limits_label.text())

    def test_generate_qr_code_shows_error_when_pillow_conversion_fails(self):
        qr = MagicMock()
        image = MagicMock()
        image.convert.side_effect = RuntimeError("pillow conversion failed")
        qr.make_image.return_value = image

        with patch("gui.qr_config_dialog.qrcode.QRCode", return_value=qr):
            dialog = QRConfigDialog()
        self.addCleanup(dialog.close)

        error_texts = [
            label.text()
            for label in dialog.findChildren(QLabel)
            if "pillow conversion failed" in label.text()
        ]

        self.assertTrue(error_texts)
        self.assertIsNone(dialog.qr_label.parent())
        qr.add_data.assert_called_once_with(dialog.generate_config_string())
        qr.make.assert_called_once_with(fit=True)


if __name__ == "__main__":
    unittest.main()
