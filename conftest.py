"""Shared pytest setup for the RollView GUI suite.

Everything here runs at import time, before any test module (and therefore
before ``settings.py``) is imported, because ``settings.ROOT_DIRECTORY`` and
``preferences.default_preferences_file_path`` are both computed from
``QDir.homePath()`` at module level.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# GUI tests must never require a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep widget grabs pixel-comparable across machines.
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("MPLBACKEND", "QtAgg")

REPO_ROOT = Path(__file__).resolve().parent
SRC = REPO_ROOT / "src"

# Redirect HOME so a test run can never read or write the real ~/.tapiorqp.
# Set ROLLVIEW_TEST_REAL_HOME=1 to opt out.
_SANDBOX_HOME = None
if os.environ.get("ROLLVIEW_TEST_REAL_HOME") != "1":
    _SANDBOX_HOME = Path(tempfile.mkdtemp(prefix="rollview-pytest-"))
    os.environ["HOME"] = str(_SANDBOX_HOME)
    os.environ["XDG_CONFIG_HOME"] = str(_SANDBOX_HOME / ".config")
    os.environ["XDG_DATA_HOME"] = str(_SANDBOX_HOME / ".local" / "share")
    os.environ["XDG_CACHE_HOME"] = str(_SANDBOX_HOME / ".cache")

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402


def pytest_unconfigure(config):
    if _SANDBOX_HOME is not None:
        shutil.rmtree(_SANDBOX_HOME, ignore_errors=True)


def pytest_addoption(parser):
    parser.addoption(
        "--leakcheck",
        action="store_true",
        help="Report QWidgets still alive after each test module, and fail if any survive.",
    )


def _live_widget_counts():
    import gc

    gc.collect()
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        return None
    return len(QApplication.allWidgets()), len(QApplication.topLevelWidgets())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Fail the last test of a module if that module left widgets alive.

    The suite is expected to end every module at zero: widgets are cheap to leak
    from a GUI test (a closed QMainWindow is not a destroyed one) and a leak
    silently changes what later tests see.
    """
    yield
    if not item.config.getoption("--leakcheck"):
        return
    module = item.module.__name__
    next_module = nextitem.module.__name__ if nextitem is not None else None
    if module == next_module:
        return
    counts = _live_widget_counts()
    if counts is None:
        return
    all_widgets, top_level = counts
    print(f"\n[leakcheck] {module}: {all_widgets} widgets alive ({top_level} top-level)")
    if all_widgets:
        from collections import Counter
        from PySide6.QtWidgets import QApplication

        classes = Counter(
            w.metaObject().className() for w in QApplication.topLevelWidgets()
        )
        for name, count in classes.most_common(10):
            print(f"[leakcheck]     {count:4d}  {name}")
        pytest.fail(
            f"{module} leaked {all_widgets} QWidget(s). Close and deleteLater() "
            f"widgets in test teardown; qtbot.addWidget() only closes them.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def app_modules():
    """Import the app through main.py so the log manager and streams exist."""
    saved_argv = sys.argv
    sys.argv = [saved_argv[0]]
    try:
        import main  # noqa: F401
    finally:
        sys.argv = saved_argv
    import settings
    import store

    return {"settings": settings, "store": store}


@pytest.fixture
def main_window(qtbot, app_modules):
    """A live MainWindow with serial scanning stubbed out.

    ``qtbot.addWidget`` only *closes* the widget at teardown, so the teardown
    below destroys it explicitly and drains the DeferredDelete queue. Without
    this a suite accumulates a MainWindow (and ~150 descendants) per test.
    """
    from unittest.mock import patch

    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
    from gui.main_window import MainWindow

    with patch("gui.main_window.SerialWidget.scan_devices"):
        window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)

    yield window

    # These two are deliberately parentless: they are separate top-level windows
    # the user opens and closes independently of the main window.
    for child in (window.settings_window, window.log_window):
        if child is not None:
            child.close()
            child.deleteLater()
    window.close()
    window.deleteLater()
    del window
    # Destroying a parent posts DeferredDelete for its children, so drain
    # repeatedly until the queue stops producing new deletions.
    for _ in range(5):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


@pytest.fixture
def snap(request, tmp_path_factory):
    """Save widget screenshots for visual review.

    ``snap(widget, "name")`` writes a PNG under ``<repo>/gui-shots/<test name>/``
    and returns its path. Override the directory with ``ROLLVIEW_SHOT_DIR``.
    """
    base = Path(os.environ.get("ROLLVIEW_SHOT_DIR", REPO_ROOT / "gui-shots"))
    out_dir = base / request.node.name.replace("/", "-")
    out_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def _snap(widget, name="shot"):
        counter["n"] += 1
        path = out_dir / f"{counter['n']:02d}-{name}.png"
        pixmap = widget.grab()
        if not pixmap.save(str(path)):
            raise RuntimeError(f"Failed to write screenshot to {path}")
        print(f"[snap] {path} ({pixmap.width()}x{pixmap.height()})")
        return path

    return _snap
