import unittest

from PySide6.QtWidgets import QApplication

from gui.widgets.ProfileWidget import ProfileWidget


class TestProfileWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()
