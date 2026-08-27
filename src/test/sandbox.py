"""Keeps a test run away from the operator's real data, and off a display.

``settings.ROOT_DIRECTORY`` and ``preferences.default_preferences_file_path``
are both computed from ``QDir.homePath()`` at *module* level, so redirecting
``HOME`` has to happen before anything imports ``settings`` — which in practice
means before the first test module is imported.

This lives here rather than in ``conftest.py`` because ``conftest.py`` is a
pytest file and the suite is also runnable with ``unittest discover``. Under
unittest there was no redirect at all, so a run wrote to the real
``~/.tapiorqp/preferences.json``. ``test/__init__.py`` is imported by both
runners before any test module, so putting it there covers both.

Set ``ROLLVIEW_TEST_REAL_HOME=1`` to opt out.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_home = None
_activated = False


def activate():
    """Redirect HOME and pin the Qt environment. Returns the sandbox, or None.

    Idempotent: whichever runner gets here first wins, and the other is a no-op.
    """
    global _home, _activated
    if _activated:
        return _home
    _activated = True

    # GUI tests must never require a display, and widget grabs have to stay
    # pixel-comparable across machines.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("MPLBACKEND", "QtAgg")

    if os.environ.get("ROLLVIEW_TEST_REAL_HOME") == "1":
        return None

    _home = Path(tempfile.mkdtemp(prefix="rollview-test-"))
    os.environ["HOME"] = str(_home)
    os.environ["XDG_CONFIG_HOME"] = str(_home / ".config")
    os.environ["XDG_DATA_HOME"] = str(_home / ".local" / "share")
    os.environ["XDG_CACHE_HOME"] = str(_home / ".cache")
    atexit.register(cleanup)
    return _home


def home():
    """The sandbox directory, or None when the run opted out."""
    return _home


def cleanup():
    global _home
    if _home is not None:
        shutil.rmtree(_home, ignore_errors=True)
        _home = None
