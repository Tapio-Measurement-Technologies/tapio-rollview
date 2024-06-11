import unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from gui.widgets.stats import StatsWidget, MeanWidget, StdWidget, CVWidget, MinWidget, MaxWidget, PeakToPeakWidget

class TestStatWidgets(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.data = np.array([1, 2, 3, 4, 5])
        self.limits = {
            "mean_g": {'name': 'mean_g', 'min': 1.0, 'max': 5.0},
            "stdev_g": {'name': 'stdev_g', 'min': 0.5, 'max': 2.0},
            "cv_pct": {'name': 'cv_pct', 'min': 10.0, 'max': 50.0},
            "min_g": {'name': 'min_g', 'min': 0.1, 'max': 1.5},
            "max_g": {'name': 'max_g', 'min': 4.5, 'max': 5.0},
            "pp_g": {'name': 'pp_g', 'min': 3.0, 'max': 4.9}
        }

    def test_mean_widget_initialization(self):
        widget = MeanWidget(self.data)
        self.assertAlmostEqual(widget.value, np.mean(self.data))
        self.assertEqual(widget.value_label.text(), f"{np.mean(self.data):.2f}")

    def test_stat_widget_tooltip(self):
        widget = MeanWidget(self.data, limit=self.limits['mean_g'])
        self.assertEqual(widget.toolTip(), "Alert Limits:\nMin: 1.0\nMax: 5.0")

    def test_stat_widget_limit_exceeded(self):
        widget = MaxWidget(self.data, limit=self.limits['max_g'])
        widget.update_data([7.0])
        self.assertTrue(widget.over_limit)
        self.assertIn("background-color: rgba(255, 0, 0, 80)", widget.styleSheet())

    def test_stats_widget_initialization(self):
        widget = StatsWidget(self.data)
        for stat_widget in widget.widgets:
            self.assertTrue(np.array_equal(stat_widget.data, self.data))

    def test_update_data(self):
        widget = StatsWidget(self.data)
        new_data = np.array([10, 20, 30, 40, 50])
        widget.update_data(new_data)
        for stat_widget in widget.widgets:
            self.assertTrue(np.array_equal(stat_widget.data, new_data))

    def test_mean_widget(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        self.assertEqual(widget.value, np.mean(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([6.0])
        self.assertTrue(widget.over_limit)

    def test_mean_widget_below_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([0.5, 0.5, 0.5])
        self.assertTrue(widget.over_limit)

    def test_mean_widget_at_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertFalse(widget.over_limit)

    def test_mean_widget_above_limit(self):
        widget = MeanWidget(self.data, self.limits['mean_g'])
        widget.update_data([6.0, 7.0, 8.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        self.assertEqual(widget.value, np.std(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget_below_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_stdev_widget_at_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertFalse(widget.over_limit)

    def test_stdev_widget_above_limit(self):
        widget = StdWidget(self.data, self.limits['stdev_g'])
        widget.update_data([1.0, 5.0, 9.0, 13.0, 17.0])
        self.assertTrue(widget.over_limit)

    def test_cv_widget(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        self.assertEqual(widget.value, (np.std(self.data) / np.mean(self.data)) * 100)
        self.assertFalse(widget.over_limit)

        widget.update_data([0.1, 0.2, 0.3, 0.4, 100])
        self.assertTrue(widget.over_limit)

    def test_cv_widget_below_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([1.0, 1.0, 1.0, 1.0])
        self.assertTrue(widget.over_limit)

    def test_cv_widget_at_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertFalse(widget.over_limit)

    def test_cv_widget_above_limit(self):
        widget = CVWidget(self.data, self.limits['cv_pct'])
        widget.update_data([1.0, 100.0, 200.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        self.assertEqual(widget.value, np.min(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([0.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget_below_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([0.0])
        self.assertTrue(widget.over_limit)

    def test_min_widget_at_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([0.1, 0.2, 0.3])
        self.assertFalse(widget.over_limit)

    def test_min_widget_above_limit(self):
        widget = MinWidget(self.data, self.limits['min_g'])
        widget.update_data([2.0, 3.0, 4.0])
        self.assertTrue(widget.over_limit)

    def test_max_widget(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        self.assertEqual(widget.value, np.max(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([7.0])
        self.assertTrue(widget.over_limit)

    def test_max_widget_below_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([4.0, 4.4])
        self.assertTrue(widget.over_limit)

    def test_max_widget_at_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([4.5, 5.0])
        self.assertFalse(widget.over_limit)

    def test_max_widget_above_limit(self):
        widget = MaxWidget(self.data, self.limits['max_g'])
        widget.update_data([5.5, 6.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        self.assertEqual(widget.value, np.max(self.data) - np.min(self.data))
        self.assertFalse(widget.over_limit)

        widget.update_data([10.0, 15.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget_below_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 2.0, 3.0])
        self.assertTrue(widget.over_limit)

    def test_peak_to_peak_widget_at_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 4.0])
        self.assertFalse(widget.over_limit)

    def test_peak_to_peak_widget_above_limit(self):
        widget = PeakToPeakWidget(self.data, self.limits['pp_g'])
        widget.update_data([1.0, 6.0])
        self.assertTrue(widget.over_limit)

if __name__ == "__main__":
    unittest.main()
