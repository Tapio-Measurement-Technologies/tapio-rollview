"""Drive the real RollView GUI headlessly and capture screenshots.

Boots the actual MainWindow (same import chain as ``src/main.py``) under the
offscreen Qt platform, inside a throwaway HOME so the user's real roll data and
preferences are never touched. A *scenario* module drives the window and calls
``ctx.snap()`` to write PNGs that can be reviewed afterwards.

Usage:
    python scripts/guiharness.py <scenario.py> [--out DIR] [--keep-home]
                                 [--home DIR] [--size WxH] [--real-serial]
                                 [--platform offscreen|xcb]

A scenario module defines ``run(ctx)``:

    def run(ctx):
        ctx.snap("startup")
        ctx.tree()
        ctx.click(ctx.find("Settings"))
        ctx.snap("settings")

Run with no scenario to just boot, dump the widget tree and snap the window.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


class Recorder:
    """Collects frames of the main window and encodes them with ffmpeg.

    Under the offscreen platform nothing paints on a timer, so frames are pulled
    explicitly: every driving action grabs one, and ``Ctx.wait()`` samples at the
    target rate while it spins the event loop. That makes a recording a faithful
    replay of what the scenario did, not a wall-clock capture.
    """

    def __init__(self, window, out_path, fps=10):
        self.window = window
        self.out_path = Path(out_path)
        self.fps = fps
        self.frame_dir = Path(tempfile.mkdtemp(prefix="rollview-frames-"))
        self.count = 0
        self._last_size = None

    def frame(self):
        from PySide6.QtCore import Qt

        if not _alive(self.window) or not self.window.isVisible():
            return
        pixmap = self.window.grab()
        if pixmap.isNull():
            return
        # ffmpeg needs every frame the same size; a resize mid-scenario would
        # otherwise abort the encode.
        if self._last_size is None:
            self._last_size = pixmap.size()
        elif pixmap.size() != self._last_size:
            pixmap = pixmap.scaled(
                self._last_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.count += 1
        pixmap.save(str(self.frame_dir / f"{self.count:05d}.png"))

    def finish(self):
        """Encode the frames. Returns the output path, or None if nothing useful."""
        if self.count < 2:
            print(f"[record] only {self.count} frame(s); skipping encode")
            shutil.rmtree(self.frame_dir, ignore_errors=True)
            return None

        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        pattern = str(self.frame_dir / "%05d.png")
        if self.out_path.suffix.lower() == ".gif":
            palette = self.frame_dir / "palette.png"
            filters = f"fps={self.fps},scale=iw:ih:flags=lanczos"
            commands = [
                ["ffmpeg", "-y", "-v", "error", "-framerate", str(self.fps),
                 "-i", pattern, "-vf", f"{filters},palettegen", str(palette)],
                ["ffmpeg", "-y", "-v", "error", "-framerate", str(self.fps),
                 "-i", pattern, "-i", str(palette),
                 "-lavfi", f"{filters}[x];[x][1:v]paletteuse", str(self.out_path)],
            ]
        else:
            commands = [
                ["ffmpeg", "-y", "-v", "error", "-framerate", str(self.fps),
                 "-i", pattern, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 # x264 needs even dimensions.
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(self.out_path)],
            ]

        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)
        except FileNotFoundError:
            print("[record] ffmpeg not found; frames left in", self.frame_dir)
            return None
        except subprocess.CalledProcessError as exc:
            print("[record] ffmpeg failed:", exc.stderr.decode(errors="replace")[:500])
            print("[record] frames left in", self.frame_dir)
            return None

        shutil.rmtree(self.frame_dir, ignore_errors=True)
        print(f"[record] {self.out_path}  ({self.count} frames @ {self.fps}fps)")
        return self.out_path


class Ctx:
    """Handle passed to a scenario: the live app plus driving/capture helpers."""

    def __init__(self, app, window, out_dir):
        self.app = app
        self.window = window
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.shots = []
        self._counter = 0
        self._open_menus = []
        self.recorder = None

    # ---------------------------------------------------------------- capture

    def snap(self, name, widget=None, settle=True):
        """Grab one widget (default: the main window) to ``<out>/NN-name.png``."""
        from PySide6.QtWidgets import QWidget

        if settle:
            self.settle()
        target = widget if widget is not None else self.window
        if not isinstance(target, QWidget):
            raise TypeError(f"snap() needs a QWidget, got {type(target).__name__}")

        self._counter += 1
        path = self.out_dir / f"{self._counter:02d}-{_slug(name)}.png"
        pixmap = target.grab()
        if not pixmap.save(str(path)):
            raise RuntimeError(f"Failed to write screenshot to {path}")
        self.shots.append(path)
        self.frame()
        print(f"[snap] {path}  ({pixmap.width()}x{pixmap.height()})")
        return path

    def snap_all(self, name, settle=True):
        """Snap every visible top-level window separately.

        Menus, dialogs and tooltips are their own top-level windows, so a plain
        ``snap()`` of the main window will not contain them.
        """
        from PySide6.QtWidgets import QApplication

        if settle:
            self.settle()
        paths = []
        for index, widget in enumerate(QApplication.topLevelWidgets()):
            if not _alive(widget) or not widget.isVisible():
                continue
            label = widget.objectName() or widget.metaObject().className()
            paths.append(self.snap(f"{name}-{index}-{label}", widget, settle=False))
        return paths

    # ---------------------------------------------------------------- driving

    def frame(self):
        """Capture one recording frame, if recording is on."""
        if self.recorder is not None:
            self.recorder.frame()

    def settle(self, rounds=3):
        """Flush pending events, layout and paints.

        Deliberately does not flush DeferredDelete: an open popup gets a pending
        deleteLater() from the offscreen platform, and draining it here would
        destroy menus and dialogs before they could be captured.
        """
        from PySide6.QtCore import QCoreApplication, QEventLoop

        for _ in range(rounds):
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        self.frame()

    def wait(self, ms):
        """Spin the event loop for ``ms`` milliseconds (keeps the GUI live)."""
        from PySide6.QtCore import QDeadlineTimer, QCoreApplication, QEventLoop

        deadline = QDeadlineTimer(ms)
        interval = 1000 // self.recorder.fps if self.recorder else None
        while not deadline.hasExpired():
            slice_ms = max(1, deadline.remainingTime())
            if interval:
                slice_ms = min(slice_ms, interval)
            QCoreApplication.processEvents(
                QEventLoop.ProcessEventsFlag.AllEvents, slice_ms
            )
            if interval:
                self.frame()

    def wait_until(self, predicate, timeout=5000, interval=50):
        """Spin until ``predicate()`` is truthy. Raises TimeoutError otherwise."""
        from PySide6.QtCore import QDeadlineTimer

        deadline = QDeadlineTimer(timeout)
        while not deadline.hasExpired():
            if predicate():
                return True
            self.wait(interval)
        raise TimeoutError(f"wait_until timed out after {timeout}ms")

    def defer(self, fn, ms=100):
        """Run ``fn`` later — the way to drive a modal dialog before opening it."""
        from PySide6.QtCore import QTimer

        QTimer.singleShot(ms, fn)

    def click(self, widget, button="left", pos=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        buttons = {
            "left": Qt.MouseButton.LeftButton,
            "right": Qt.MouseButton.RightButton,
            "middle": Qt.MouseButton.MiddleButton,
        }
        widget = self._resolve(widget)
        QTest.mouseClick(widget, buttons[button], pos=pos or widget.rect().center())
        self.settle()

    def double_click(self, widget, pos=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        widget = self._resolve(widget)
        QTest.mouseDClick(
            widget, Qt.MouseButton.LeftButton, pos=pos or widget.rect().center()
        )
        self.settle()

    def type(self, text, widget=None):
        from PySide6.QtTest import QTest

        QTest.keyClicks(self._resolve(widget) if widget is not None else self.focused(), text)
        self.settle()

    def key(self, key_name, widget=None, modifiers=None):
        """``ctx.key("Return")``, ``ctx.key("A", modifiers="Ctrl")``."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        key = getattr(Qt.Key, key_name if key_name.startswith("Key_") else f"Key_{key_name}")
        mods = Qt.KeyboardModifier.NoModifier
        for name in (modifiers or "").split("+"):
            if name:
                mods |= getattr(Qt.KeyboardModifier, f"{name}Modifier")
        QTest.keyClick(
            self._resolve(widget) if widget is not None else self.focused(), key, mods
        )
        self.settle()

    def focused(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.focusWidget() or self.window

    # ------------------------------------------------------------ inspection

    def find(self, text, kind=None, root=None, index=0):
        """Find a descendant widget by objectName, text, title or placeholder.

        ``kind`` narrows by class name, e.g. ``ctx.find("Sync", kind="QPushButton")``.
        """
        matches = self.find_all(text, kind=kind, root=root)
        if not matches:
            raise LookupError(
                f"No widget matching {text!r}"
                + (f" of kind {kind!r}" if kind else "")
                + ". Call ctx.tree() to see what exists."
            )
        return matches[index]

    def find_all(self, text=None, kind=None, root=None):
        from PySide6.QtWidgets import QWidget

        root = root if root is not None else self.window
        out = []
        for widget in root.findChildren(QWidget):
            if kind and widget.metaObject().className() != kind:
                continue
            if text is not None and text.lower() not in _labels(widget).lower():
                continue
            out.append(widget)
        return out

    def action(self, text, root=None):
        """Find a QAction (menu item) by its text."""
        from PySide6.QtGui import QAction

        root = root if root is not None else self.window
        wanted = text.lower().replace("&", "")
        for act in root.findChildren(QAction):
            if wanted in act.text().lower().replace("&", ""):
                return act
        raise LookupError(f"No QAction matching {text!r}. Call ctx.menus() to list them.")

    def open_menu(self, title, at=None):
        """Pop up a menubar menu and return it, ready to ``snap()``.

        A popped-up QMenu is its own top-level window, so it never appears in a
        ``snap()`` of the main window. Both the menu and the QAction it came from
        are parked on the Ctx: the QAction wrappers handed out by
        ``menuBar().actions()`` are transient, and letting one go out of scope
        takes its QMenu's C++ object down with it.
        """
        wanted = title.lower().replace("&", "")
        for menu_action in self.window.menuBar().actions():
            if wanted in menu_action.text().lower().replace("&", ""):
                menu = menu_action.menu()
                if menu is None:
                    raise LookupError(f"Menubar entry {title!r} has no submenu")
                self._open_menus.append((menu_action, menu))
                menu.popup(self.window.mapToGlobal(at or self.window.rect().topLeft()))
                self.settle()
                return menu
        raise LookupError(f"No menubar entry matching {title!r}")

    def close_menus(self):
        for _action, menu in self._open_menus:
            if _alive(menu):
                menu.close()
        self._open_menus.clear()
        self.settle()

    def menus(self):
        """Print every menu action in the menubar."""
        bar = self.window.menuBar()
        for menu_action in bar.actions():
            menu = menu_action.menu()
            print(f"{menu_action.text()}")
            if menu is None:
                continue
            for act in menu.actions():
                if act.isSeparator():
                    print("    ---")
                    continue
                flags = []
                if act.isCheckable():
                    flags.append("checked" if act.isChecked() else "unchecked")
                if not act.isEnabled():
                    flags.append("disabled")
                if act.menu() is not None:
                    flags.append("submenu")
                suffix = f"  [{', '.join(flags)}]" if flags else ""
                print(f"    {act.text()}{suffix}")

    def tree(self, root=None, max_depth=12, visible_only=True):
        """Print the live widget hierarchy — the map for deciding what to click."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget

        direct_only = Qt.FindChildOption.FindDirectChildrenOnly
        root = root if root is not None else self.window

        def walk(widget, depth):
            if depth > max_depth:
                return
            label = _labels(widget).strip()
            geom = widget.geometry()
            marks = []
            if not widget.isVisible():
                marks.append("hidden")
            if not widget.isEnabled():
                marks.append("disabled")
            suffix = f" ({', '.join(marks)})" if marks else ""
            print(
                f"{'  ' * depth}{widget.metaObject().className()}"
                f"{' ' + label if label else ''}"
                f" [{geom.width()}x{geom.height()} @{geom.x()},{geom.y()}]{suffix}"
            )
            for child in widget.findChildren(QWidget, options=direct_only):
                if visible_only and not child.isVisible():
                    continue
                walk(child, depth + 1)

        walk(root, 0)

    def _resolve(self, widget):
        return self.find(widget) if isinstance(widget, str) else widget


def _alive(obj):
    """False once Qt has deleted the underlying C++ object (popups do this a lot)."""
    import shiboken6

    return shiboken6.isValid(obj)


def _labels(widget):
    """Every user-visible string a widget exposes, joined for matching."""
    parts = [widget.objectName()]
    for getter in ("text", "title", "windowTitle", "placeholderText", "toolTip"):
        fn = getattr(widget, getter, None)
        if callable(fn):
            try:
                value = fn()
            except TypeError:
                continue
            if isinstance(value, str) and value:
                parts.append(value)
    return " | ".join(p for p in parts if p)


def _slug(name):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(name)).strip("-")


def _sandbox_home(base=None):
    home = Path(base) if base else Path(tempfile.mkdtemp(prefix="rollview-gui-"))
    home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(home)
    os.environ["XDG_CONFIG_HOME"] = str(home / ".config")
    os.environ["XDG_DATA_HOME"] = str(home / ".local" / "share")
    os.environ["XDG_CACHE_HOME"] = str(home / ".cache")
    return home


def boot(size=(1280, 800), real_serial=False, out_dir=".", local_settings=None,
         record=None, fps=10):
    """Import the app the way main.py does, build MainWindow, return a Ctx."""
    sys.path.insert(0, str(SRC))

    # settings.py execs sys.argv[1] as a local_settings module and main.py parses
    # --settings-file, both at import time. Hand them a clean argv so harness
    # flags are never mistaken for app arguments.
    real_argv = sys.argv
    sys.argv = [real_argv[0]] + ([str(local_settings)] if local_settings else [])
    try:
        import main  # noqa: F401  -- sets up log manager, streams and excepthook
    finally:
        sys.argv = real_argv

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    import settings

    app = QApplication.instance() or QApplication([sys.argv[0]])

    # main() applies the Tapio Design System before building any widget; the
    # harness has to do the same or it screenshots an unstyled application.
    import theme
    from utils import preferences

    theme.apply(app, theme=preferences.ui_theme)

    from gui.main_window import MainWindow
    from gui.widgets.serialports import SerialWidget

    if not real_serial:
        # Never touch real hardware from a harness run; the scan also fires a
        # background thread that would keep the event loop busy.
        SerialWidget.scan_devices = lambda self: None

    window = MainWindow()
    icon = QIcon(settings.ICON_PATH)
    app.setWindowIcon(icon)
    window.setWindowIcon(icon)
    window.resize(*size)
    window.show()

    ctx = Ctx(app, window, out_dir)
    if record:
        ctx.recorder = Recorder(window, record, fps=fps)
    ctx.settle()
    return ctx


def load_scenario(path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"scenario_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        raise SystemExit(f"{path} defines no run(ctx) function")
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", help="Python file defining run(ctx)")
    parser.add_argument("--out", default=None, help="Screenshot output directory")
    parser.add_argument("--home", default=None, help="Sandbox HOME to use (reused if it exists)")
    parser.add_argument("--keep-home", action="store_true", help="Do not delete the sandbox HOME")
    parser.add_argument("--size", default="1280x800", help="Main window size, WxH")
    parser.add_argument("--real-serial", action="store_true", help="Allow real serial port scanning")
    parser.add_argument(
        "--record",
        default=None,
        metavar="PATH",
        help="Record the run to a .gif or .mp4 (needs ffmpeg)",
    )
    parser.add_argument("--fps", type=int, default=10, help="Recording frame rate")
    parser.add_argument(
        "--local-settings",
        default=None,
        help="Path to a local_settings.py to override src/settings.py values",
    )
    parser.add_argument(
        "--platform",
        default="offscreen",
        help="Qt platform plugin (offscreen, or xcb under Xvfb)",
    )
    args = parser.parse_args()

    os.environ["QT_QPA_PLATFORM"] = args.platform
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")
    # Keep grabs pixel-comparable between runs and machines.
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("MPLBACKEND", "QtAgg")

    home = _sandbox_home(args.home)
    keep_home = args.keep_home or args.home is not None

    out_dir = args.out or (REPO_ROOT / "gui-shots")
    width, height = (int(v) for v in args.size.lower().split("x"))

    print(f"[harness] HOME={home}")
    print(f"[harness] platform={args.platform} out={out_dir}")

    exit_code = 0
    try:
        ctx = boot(
            size=(width, height),
            real_serial=args.real_serial,
            out_dir=out_dir,
            local_settings=args.local_settings,
            record=args.record,
            fps=args.fps,
        )
        if args.scenario:
            load_scenario(args.scenario).run(ctx)
        else:
            ctx.tree()
            print()
            ctx.menus()
            ctx.snap("startup")

        if ctx.recorder is not None:
            ctx.recorder.finish()

        if ctx.shots:
            print(f"\n[harness] {len(ctx.shots)} screenshot(s):")
            for shot in ctx.shots:
                print(f"  {shot}")
    except Exception:
        import traceback

        traceback.print_exc()
        exit_code = 1
    finally:
        if not keep_home:
            shutil.rmtree(home, ignore_errors=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
