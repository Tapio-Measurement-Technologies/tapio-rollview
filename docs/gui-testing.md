# GUI testing

Four tools, all fully headless — no display and no RQFT hardware required. The
two that run the app sandbox `HOME`, so a run can never touch the real
`~/.tapiorqp`.

## 1. pytest + pytest-qt

`pytest.ini` and the root `conftest.py` add pytest on top of the existing
`unittest` suite. Both runners work; CI still uses `unittest`.

```bash
.venv/bin/python -m pytest
```

Fixtures from `conftest.py`:

| Fixture | What it gives you |
| --- | --- |
| `main_window` | A live `MainWindow`, serial scanning stubbed, destroyed at teardown |
| `snap` | `snap(widget, "name")` writes a PNG under `gui-shots/<test name>/` |
| `app_modules` | Session-scoped import of `main`/`settings`/`store` the way `main.py` does it |
| `qtbot` | pytest-qt's driver: `mouseClick`, `keyClicks`, `waitUntil`, `waitSignal` |

`src/test/test_gui_visual.py` is a worked example.

```python
def test_switch_to_statistics_tab(main_window, qtbot, snap):
    tab_bar = main_window.tab_view.tabBar()
    qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar.tabRect(1).center())
    assert main_window.tab_view.currentIndex() == 1
    snap(main_window, "statistics-tab")
```

### Widget leak check

```bash
.venv/bin/python -m pytest --leakcheck
```

Fails the last test of any module that left `QWidget`s alive. The suite is
expected to end every module at zero, and does. This matters more than it
sounds: `qtbot.addWidget()` only *closes* a widget, it does not destroy it, so a
naive fixture accumulates a whole `MainWindow` tree per test and later tests
start seeing state left by earlier ones.

Note `SerialWidget.transferDialog` is built with no parent
(`gui/widgets/serialports.py`), so Qt's parent-child ownership never reclaims it;
the `main_window` fixture closes it explicitly.

### Qt warnings are failures

`pytest.ini` sets `qt_log_level_fail = WARNING`. Qt reports real bugs at warning
level and nothing else notices them: layout misuse, cross-thread pixmap access,
`QThread: Destroyed while thread is still running`. Known-benign messages are
listed individually under `qt_log_ignore` rather than lowering the bar globally —
today that is only the offscreen plugin narrating what it cannot do.

Note a Qt warning raised from a worker thread aborts the process rather than
failing the test cleanly, so a new failure here may show up as
`Fatal Python error: Aborted` instead of a normal report. Run the suspect file on
its own with `-o qt_log_level_fail=NO` to see the message.

## 2. `scripts/guiharness.py` — exploratory runs

Boots the real app and runs a *scenario*, for looking at the GUI rather than
asserting on it.

```bash
# Boot, dump the widget tree and menus, screenshot the window
.venv/bin/python scripts/guiharness.py

# Run a scenario
.venv/bin/python scripts/guiharness.py scripts/scenarios/overview.py --out /tmp/shots
```

A scenario is a Python file defining `run(ctx)`:

```python
def run(ctx):
    ctx.snap("startup")
    ctx.window.tab_view.setCurrentIndex(1)
    ctx.snap("statistics")

    menu = ctx.open_menu("View")
    ctx.snap("view-menu", menu)
    ctx.close_menus()
```

### `ctx` reference

**Capture** — `snap(name, widget=None)`, `snap_all(name)` (every visible
top-level window, which is how you catch menus, dialogs and tooltips).

**Driving** — `click`, `double_click`, `type`, `key`, `settle`, `wait(ms)`,
`wait_until(pred)`, `defer(fn, ms)` (schedule an action *before* opening a modal,
since `exec()` blocks).

**Inspection** — `tree()` prints the live widget hierarchy with geometry and
enabled/visible state; `menus()` prints every menubar action; `find(text, kind=)`
and `find_all()` match on objectName, text, title, placeholder or tooltip;
`action(text)` finds a `QAction`.

### Flags

| Flag | Effect |
| --- | --- |
| `--out DIR` | Screenshot directory (default `gui-shots/`) |
| `--size WxH` | Main window size (default 1280x800) |
| `--home DIR` | Reuse a sandbox HOME instead of a throwaway one (implies `--keep-home`) |
| `--keep-home` | Don't delete the sandbox HOME on exit |
| `--real-serial` | Allow real serial port scanning (off by default — the harness must not touch hardware) |
| `--local-settings PATH` | Load a `local_settings.py` override |
| `--platform` | Qt platform plugin, default `offscreen` |
| `--record PATH` | Record the run to a `.gif` or `.mp4` (needs ffmpeg) |
| `--fps N` | Recording frame rate, default 10 |

### Recording a run

```bash
.venv/bin/python scripts/guiharness.py scripts/scenarios/sync_demo.py \
    --real-serial --record sync.gif
```

Nothing paints on a timer under the offscreen platform, so frames are pulled
explicitly: every driving action captures one and `ctx.wait()` samples at the
target rate. A recording is therefore a replay of what the scenario did rather
than a wall-clock capture. Call `ctx.frame()` to force an extra frame.

## 3. `src/test/fakedevice.py` — a fake RQFT device

The device workflow — scan, read device info, pull profiles over ZMODEM — used to
be reachable only by mocking `serial.Serial`, which skips the protocol entirely.
`FakeRqftDevice` puts a real file descriptor on the other end instead:
`pty.openpty()` gives a `/dev/pts/N` that pyserial opens exactly as it would a
physical device.

```python
from test.fakedevice import FakeRqftDevice, make_profile_bytes

with FakeRqftDevice(profiles={"250520-134139/a.prof": make_profile_bytes()}) as device, \
        device.patch_comports():
    ...  # the app can now scan, find the device, and sync from it
```

- `patch_comports()` makes `list_ports.comports()` report the fake (with a VID/PID
  the scanner accepts) and nothing real.
- `make_profile_bytes()` builds a valid `.prof` payload, so synced files actually
  parse and plot. Without arguments it produces a plausible roll profile.
- `commands`, `timestamps`, `files_sent` and `errors` record what the app did, for
  asserting on. `wait_for(predicate)` bridges the thread boundary — the device
  runs on its own thread, so never assert immediately after the call that
  triggered a write.
- `respond_to_deviceinfo=False` simulates a silent port.

`src/modem` implements ZMODEM *receive* only, so the sender here is written
against that receiver: binary headers with 16-bit CRCs throughout, one ZDATA
frame per file. It reuses the app's own `crc16`, so the two cannot silently
disagree.

Worked examples: `src/test/test_fake_device.py` (protocol level) and
`src/test/test_gui_device_sync.py` (the same flow driven through the real GUI,
with screenshots). `scripts/scenarios/sync_demo.py` records the whole thing.

## 4. `scripts/contactsheet.py` — review many shots at once

```bash
# One labelled grid instead of a dozen separate images
.venv/bin/python scripts/contactsheet.py gui-shots/ -o sheet.png --cols 4

# Box what changed against a baseline run
.venv/bin/python scripts/contactsheet.py gui-shots/ --baseline gui-shots-main/ -o diff.png
```

`--baseline` outlines changed regions in red and prints a changed-pixel count per
shot, which is how you check whether a change moved anything it should not have.

## Notes

- **Sandboxing.** Both paths point `HOME` at a temp directory before `settings.py`
  is imported, because `settings.ROOT_DIRECTORY` and the preferences path are
  computed from `QDir.homePath()` at module import time. Set
  `ROLLVIEW_TEST_REAL_HOME=1` to opt out under pytest. Note the plain
  `unittest` runner has no such sandbox and *does* write to the real
  `~/.tapiorqp/preferences.json`.
- **argv.** `settings.py` execs `sys.argv[1]` as a `local_settings` module and
  `main.py` parses `--settings-file`, both at import time. The harness hands them
  a scrubbed argv so its own flags are never mistaken for app arguments.
- **Popup lifetime.** A `QMenu` obtained from `menuBar().actions()` is kept alive
  only by its `QAction` wrapper; drop that reference and the C++ object is
  destroyed. `ctx.open_menu()` holds both. Similarly, `ctx.settle()` deliberately
  does not flush `DeferredDelete` events.
- **`--platform xcb`** renders through a real X server and is more faithful than
  offscreen — the status bar hint, for one, only appears under xcb. Use it when a
  screenshot looks wrong under offscreen. Needs
  `libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1`; Qt's own error message
  misleadingly blames `libxcb-cursor0`, so run `ldd` on
  `PySide6/Qt/plugins/platforms/libqxcb.so` to see what is actually missing.
  ```
  xvfb-run -a .venv/bin/python scripts/guiharness.py --platform xcb
  ```
