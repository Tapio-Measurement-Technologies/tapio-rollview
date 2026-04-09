import unittest

import settings
from PySide6.QtWidgets import QApplication

from gui.widgets.ProfileWidget import ProfileWidget
from utils import preferences


class TestProfileWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        self.original_distance_unit = preferences.distance_unit

    def tearDown(self):
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions
        preferences.distance_unit = self.original_distance_unit

    def test_sync_toolbar_layout_positions_updates_saved_home_geometry(self):
        widget = ProfileWidget()
        try:
            widget.profile_ax.plot([0, 1], [0, 1])
            widget.figure.tight_layout()
            widget._reset_toolbar_history()

            nav_state = widget.toolbar._nav_stack._elements[0]
            _, (_, (_, original_active_pos)) = next(iter(nav_state.items()))

            widget.figure.subplots_adjust(left=0.25, right=0.95, bottom=0.22, top=0.88)
            widget._sync_toolbar_layout_positions()

            _, (_, (_, synced_active_pos)) = next(iter(nav_state.items()))
            current_active_pos = widget.profile_ax.get_position().frozen()

            self.assertNotEqual(original_active_pos.bounds, synced_active_pos.bounds)
            self.assertEqual(synced_active_pos.bounds, current_active_pos.bounds)
        finally:
            widget.close()

    def test_absolute_excluded_region_plot_ranges_follow_selected_distance_unit(self):
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_ABSOLUTE
        preferences.excluded_regions = "1-2"
        preferences.distance_unit = "in"

        widget = ProfileWidget()
        try:
            conversion_factor = preferences.get_distance_unit_info().conversion_factor
            plot_ranges = widget._get_excluded_region_plot_ranges([0.0, 1.0, 2.0, 3.0], conversion_factor)

            self.assertEqual(len(plot_ranges), 1)
            self.assertAlmostEqual(plot_ranges[0][0], 1.0)
            self.assertAlmostEqual(plot_ranges[0][1], 2.0)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
