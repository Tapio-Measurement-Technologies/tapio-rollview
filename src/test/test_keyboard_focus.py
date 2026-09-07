"""Where the keyboard is left pointing after a button does its work.

Qt gives the focus of a widget it disables to the next one in the tab
order, which is how a press on Scan handed the caret to the folder filter
two panels down. These need the whole window: the widget the focus wrongly
landed on lives in a different panel from the button that lost it, and
``hasFocus`` is only true on a window that has been shown.
"""

from PySide6.QtCore import Qt


def press_scan(window):
    """Press Scan the way a mouse does: the button takes the focus first."""
    button = window.serial_widget.scanButton
    button.setFocus(Qt.FocusReason.MouseFocusReason)
    assert button.hasFocus(), "the button under test never held the focus"
    window.serial_widget.scan_devices()


def test_scanning_does_not_hand_the_caret_to_the_folder_filter(main_window):
    press_scan(main_window)

    assert main_window.focusWidget() is main_window.serial_widget.view, (
        f"focus left the device panel for "
        f"{type(main_window.focusWidget()).__name__}"
    )


def test_the_scan_button_gets_the_focus_back_when_the_pass_ends(main_window):
    """So a second pass is another press of the space bar, not a hunt."""
    press_scan(main_window)

    main_window.serial_widget.on_scan_finished([])

    assert main_window.focusWidget() is main_window.serial_widget.scanButton


def test_an_operator_who_moved_on_during_the_pass_keeps_where_they_moved(main_window):
    """A pass runs for seconds; the focus is offered back, never taken."""
    press_scan(main_window)
    filter_input = main_window.directory_view.rollFilterInput
    filter_input.setFocus(Qt.FocusReason.MouseFocusReason)

    main_window.serial_widget.on_scan_finished([])

    assert main_window.focusWidget() is filter_input


def test_the_scan_at_start_up_moves_no_focus(main_window):
    """The window scans itself on opening, with the button untouched."""
    filter_input = main_window.directory_view.rollFilterInput
    filter_input.setFocus(Qt.FocusReason.MouseFocusReason)

    main_window.serial_widget.scan_devices()
    assert main_window.focusWidget() is filter_input

    main_window.serial_widget.on_scan_finished([])
    assert main_window.focusWidget() is filter_input
