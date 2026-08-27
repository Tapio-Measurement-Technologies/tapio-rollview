"""Walk every surface the Tapio Design System touches, and screenshot each one.

Written for reviewing the *look* rather than asserting on it: run it, build a
contact sheet, and check the result against the design guide and its QA
checklist.

    .venv/bin/python scripts/guiharness.py scripts/scenarios/design_review.py \\
        --home /tmp/rollview-review --out gui-shots/light

    # The same walk in the other theme — dark is a real theme, not light with
    # inverted colours, so it gets reviewed in full too.
    ROLLVIEW_REVIEW_THEME=dark .venv/bin/python scripts/guiharness.py \\
        scripts/scenarios/design_review.py --home /tmp/rollview-review-dark \\
        --out gui-shots/dark

    .venv/bin/python scripts/contactsheet.py gui-shots/light -o light.png --cols 3

The sandbox HOME needs roll data in it to be worth looking at; without any the
scenario still runs and captures the empty states, which are also part of the
system.
"""

import os


def _retheme(ctx):
    """Honour ROLLVIEW_REVIEW_THEME, so one scenario covers both themes."""
    wanted = os.environ.get("ROLLVIEW_REVIEW_THEME")
    if not wanted:
        return
    ctx.window.apply_appearance(wanted)
    ctx.settle()


def run(ctx):
    from PySide6.QtWidgets import QListWidget

    _retheme(ctx)

    # ---- the shell -------------------------------------------------------
    ctx.snap("01-shell-profiles")

    ctx.window.tab_view.setCurrentIndex(1)
    ctx.wait(600)
    ctx.snap("02-shell-statistics")
    ctx.window.tab_view.setCurrentIndex(0)
    ctx.settle()

    # ---- chrome ----------------------------------------------------------
    for title in ("File", "View", "Postprocessors", "Device configuration"):
        try:
            menu = ctx.open_menu(title)
        except LookupError as exc:
            print(f"[skip] {exc}")
            continue
        ctx.snap(f"03-menu-{title}", menu)
        ctx.close_menus()

    # ---- the stat tile's editor, which is also the form pattern ----------
    # exec() blocks, so the capture and the close have to be queued *before* it.
    tiles = ctx.window.profile_widget.stats_widget.widgets
    if tiles:
        ctx.defer(lambda: ctx.snap_all("04-alert-limit-editor"), 400)
        ctx.defer(lambda: _close_modal(ctx), 900)
        tiles[0].open_alert_limit_editor()
        ctx.settle()

    # ---- settings, page by page -----------------------------------------
    ctx.action("Settings").trigger()
    ctx.wait_until(lambda: ctx.window.settings_window is not None)
    settings_window = ctx.window.settings_window

    nav = settings_window.findChild(QListWidget)
    if nav is not None:
        for row in range(nav.count()):
            nav.setCurrentRow(row)
            ctx.settle()
            ctx.snap(f"05-settings-{nav.item(row).text()}", settings_window)

    # A highlight row is the densest form in the product: several numeric
    # fields, a mode select and the colour picker on one line.
    highlights = getattr(settings_window, "distance_highlights_page", None)
    if highlights is not None:
        nav.setCurrentRow(_row_named(nav, "highlight"))
        ctx.settle()
        highlights.add_empty_row()
        ctx.settle()
        ctx.snap("06-settings-highlight-row", settings_window)

    settings_window.close()
    ctx.settle()

    # ---- the log window --------------------------------------------------
    ctx.action("Application logs").trigger()
    ctx.wait_until(lambda: ctx.window.log_window is not None)
    ctx.snap("07-log-window", ctx.window.log_window)
    ctx.window.log_window.close()
    ctx.settle()

    # ---- the device configuration dialog --------------------------------
    # This one is show()n rather than exec()d, so it is captured the normal way:
    # a deferred call would never fire, since nothing spins the loop meanwhile.
    ctx.action("Apply alert limits to device").trigger()
    ctx.wait(600)
    ctx.snap_all("08-qr-config")
    _close_modal(ctx)
    ctx.settle()

    # ---- the file transfer dialog ---------------------------------------
    transfer_dialog = ctx.window.serial_widget.transferDialog
    transfer_dialog.show()
    ctx.settle()
    ctx.snap("09-file-transfer", transfer_dialog)
    transfer_dialog.close()
    ctx.settle()

    # ---- the empty states ------------------------------------------------
    ctx.window.profile_widget.clear_plot_display()
    ctx.settle()
    ctx.snap("10-empty-state")


def _row_named(nav, needle):
    for row in range(nav.count()):
        if needle.lower() in nav.item(row).text().lower():
            return row
    return 0


def _close_modal(ctx):
    from PySide6.QtWidgets import QApplication, QDialog

    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QDialog) and widget.isVisible():
            widget.reject()
