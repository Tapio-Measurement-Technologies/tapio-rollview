"""Example: drive the real MainWindow with qtbot and capture what it looks like.

Not a regression test — a worked example of the interaction + screenshot
capability. Run it with:

    .venv/bin/python -m pytest src/test/test_gui_visual.py -s
"""

import numpy as np
from PySide6.QtCore import Qt


def test_startup_window(main_window, snap):
    snap(main_window, "startup")
    assert main_window.tab_view.count() == 2
    assert main_window.tab_view.tabText(0)


def test_switch_to_statistics_tab(main_window, qtbot, snap):
    tab_bar = main_window.tab_view.tabBar()
    qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar.tabRect(1).center())
    assert main_window.tab_view.currentIndex() == 1
    snap(main_window, "statistics-tab")


def test_profile_plot_renders(main_window, snap):
    from models.Profile import Profile, ProfileData, ProfileHeader

    distances = np.linspace(0.0, 12.0, 600)
    hardness = 40.0 + 6.0 * np.sin(distances * 1.4)
    profile = Profile(
        path="synthetic.prof",
        data=ProfileData(distances=distances, hardnesses=hardness),
        header=ProfileHeader(prof_version=1, serial_number="SN0", sample_step=0.02),
        file_size=distances.size * 4,
        date_modified=0.0,
    )

    main_window.profile_widget.update_plot([profile], "synthetic-roll")
    snap(main_window.profile_widget, "profile-plot")


def test_settings_window_opens(main_window, qtbot, snap):
    from PySide6.QtGui import QAction

    action = next(
        a for a in main_window.findChildren(QAction)
        if "settings" in a.text().lower() and "file" not in a.text().lower()
    )
    action.trigger()
    qtbot.waitUntil(lambda: main_window.settings_window is not None)
    snap(main_window.settings_window, "settings-window")
