
# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.
import sys
import os
import settings

# Fix unavailable handles for pyinstaller --noconsole in Windows
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()

    app_icon = QIcon(os.path.join('assets', 'tapio192.png'))
    app.setWindowIcon(app_icon)
    window.setWindowIcon(app_icon)

    window.show()
    return app.exec()


if __name__ == '__main__':
    main()
