"""Walk the main surfaces of the app and screenshot each one.

    .venv/bin/python scripts/guiharness.py scripts/scenarios/overview.py
"""


def run(ctx):
    ctx.snap("01-startup")

    ctx.window.tab_view.setCurrentIndex(1)
    ctx.wait(300)
    ctx.snap("02-statistics")
    ctx.window.tab_view.setCurrentIndex(0)

    for title in ("File", "View", "Postprocessors", "Device configuration"):
        try:
            menu = ctx.open_menu(title)
        except LookupError as exc:
            print(f"[skip] {exc}")
            continue
        ctx.snap(f"menu-{title}", menu)
        ctx.close_menus()

    ctx.action("Settings").trigger()
    ctx.wait_until(lambda: ctx.window.settings_window is not None)
    settings_window = ctx.window.settings_window
    ctx.snap("settings", settings_window)

    # Every page of the settings sidebar.
    from PySide6.QtWidgets import QListWidget

    sidebar = settings_window.findChild(QListWidget)
    if sidebar is not None:
        for row in range(sidebar.count()):
            sidebar.setCurrentRow(row)
            ctx.settle()
            ctx.snap(f"settings-{sidebar.item(row).text()}", settings_window)
