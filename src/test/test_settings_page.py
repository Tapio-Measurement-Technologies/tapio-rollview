import unittest

from PySide6.QtWidgets import QApplication

import settings
from gui.settings import AdvancedSettingsPage
from utils import preferences


class TestAdvancedSettingsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions

        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_RELATIVE
        preferences.excluded_regions = ""

        self.page = AdvancedSettingsPage()

    def tearDown(self):
        self.page.close()
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions

    def _set_mode(self, mode):
        self.page.excluded_regions_mode_selector.setCurrentText(
            self.page.excluded_regions_modes[mode]
        )

    def test_switching_relative_to_absolute_keeps_text_unchanged(self):
        self.page.excluded_regions_input.setText("20-80")

        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)

        self.assertEqual(self.page.excluded_regions_input.text(), "20-80")

    def test_switching_absolute_to_relative_keeps_text_unchanged(self):
        self._set_mode(settings.EXCLUDED_REGIONS_MODE_ABSOLUTE)
        self.page.excluded_regions_input.setText("2-8")

        self._set_mode(settings.EXCLUDED_REGIONS_MODE_RELATIVE)

        self.assertEqual(self.page.excluded_regions_input.text(), "2-8")


if __name__ == "__main__":
    unittest.main()
