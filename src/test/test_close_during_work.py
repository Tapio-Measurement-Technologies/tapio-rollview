"""Closing the window while background threads are running must not abort.

Qt aborts the process if a QThread is destroyed while its OS thread is still
running, so closeEvent has to bring the scan, the transfer and any postprocessing
down first. These tests close the window mid-flight against a fake RQFT device;
with pytest.ini's qt_log_level_fail, a regression surfaces as
"QThread: Destroyed while thread is still running".
"""

import pytest

# The fake device puts a real file descriptor on the other end of the serial
# port, and a pseudo-terminal is the POSIX way to get one. RollView ships on
# Windows too, where `pty` does not exist and a bare import would fail the whole
# module at collection rather than skipping it.
pytest.importorskip("pty", reason="the fake RQFT device needs a POSIX pseudo-terminal")

from test.fakedevice import FakeRqftDevice, make_profile_bytes

# Big enough that the transfer is still in flight when the window is closed.
BIG_PROFILE = make_profile_bytes([40.0 + (i % 20) for i in range(4000)])


@pytest.fixture
def device():
    with FakeRqftDevice(
        profiles={f"250520-134139/{n}.prof": BIG_PROFILE for n in "abcd"},
        device_name="RQP Fake",
    ) as fake:
        yield fake


@pytest.fixture
def wired_window(main_window, device):
    with device.patch_comports():
        yield main_window


def test_close_during_scan_stops_the_scanner(wired_window, qtbot):
    serial_widget = wired_window.serial_widget
    serial_widget.scan_devices()
    assert serial_widget.scanner.is_running()

    wired_window.close()

    assert not serial_widget.scanner.is_running()


def test_close_during_transfer_stops_the_worker(wired_window, qtbot):
    serial_widget = wired_window.serial_widget
    with qtbot.waitSignal(serial_widget.scan_finished, timeout=15000):
        serial_widget.scan_devices()

    port_item = next(p for p in serial_widget.view.model.ports if p.device_responded)
    serial_widget.view.model.selected_port = port_item

    with qtbot.waitSignal(serial_widget.transferManager.transferStarted, timeout=5000):
        serial_widget.sync_data()
    assert serial_widget.transferManager.is_transfer_in_progress()

    wired_window.close()

    assert not serial_widget.transferManager.is_transfer_in_progress()


def test_stop_background_workers_is_safe_when_nothing_is_running(main_window):
    """Closing an idle window must not raise or block."""
    assert main_window.stop_background_workers() is True
    assert main_window.stop_background_workers() is True


def test_transfer_finished_means_the_thread_has_exited(
    wired_window, device, qtbot, tmp_path
):
    """transferFinished must not arrive while the worker thread is still alive.

    This is what lets a listener close the window from that signal.
    """
    import store

    store.root_directory = str(tmp_path)
    serial_widget = wired_window.serial_widget

    with qtbot.waitSignal(serial_widget.scan_finished, timeout=15000):
        serial_widget.scan_devices()
    port_item = next(p for p in serial_widget.view.model.ports if p.device_responded)
    serial_widget.view.model.selected_port = port_item

    manager = serial_widget.transferManager
    thread_alive_at_signal = []
    manager.transferFinished.connect(
        lambda *_: thread_alive_at_signal.append(
            manager.thread is not None and manager.thread.isRunning()
        )
    )

    with qtbot.waitSignal(manager.transferFinished, timeout=30000):
        serial_widget.sync_data()

    assert thread_alive_at_signal == [False]
