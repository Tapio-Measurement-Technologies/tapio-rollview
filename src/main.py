
# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.
from utils.log_stream import EmittingStream, EmittingStreamType

# Replaces sys.stdout and sys.stderr
stdout_stream = EmittingStream(EmittingStreamType.STDOUT)
stderr_stream = EmittingStream(EmittingStreamType.STDERR)

from utils.logging import LogManager
import settings
import store
store.log_manager = LogManager(stdout_stream, stderr_stream, settings.LOG_WINDOW_MAX_LINES, settings.LOG_WINDOW_SHOW_TIMESTAMPS)

import sys
import os
import traceback

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow Ctrl+C to exit as usual
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Format traceback
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    store.log_manager.handle_crash(tb)

# Set global exception handler
sys.excepthook = handle_exception

def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from gui.main_window import MainWindow

    # Fix Windows taskbar icon
    if sys.platform == 'win32':
        import ctypes
        myappid = 'tapio.rollview'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QApplication(sys.argv)
    window = MainWindow()

    app_icon = QIcon(settings.ICON_PATH)
    app.setWindowIcon(app_icon)
    window.setWindowIcon(app_icon)

    window.show()
    return app.exec()

# Show splash screen on standalone pyinstaller executable
try:
    import pyi_splash
    pyi_splash.update_text("Loading Tapio RollView...")
    pyi_splash.close()
except:
    print('Skipping splash screen...')
    pass

if __name__ == '__main__':
    main()
