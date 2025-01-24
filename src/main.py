
# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.
import sys
import os

# Fix unavailable handles for pyinstaller --noconsole in Windows
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import gettext
import locale

def main():
    # Initialize translations
    locale.setlocale(locale.LC_ALL, '')  # Use user's locale
    lang, encoding = locale.getlocale()  # Get the current locale and encoding
    if lang is None:
        lang = 'en'  # Fallback to a default language if the locale is not set
    locale_dir = os.path.join(os.path.dirname(__file__), "locales")

    if lang.startswith('en'):
        lang = 'en'  # Treat all English locales as "en"

    print(f"Detected locale: '{lang}'")

    # Set up gettext
    try:
        gettext.bindtextdomain('messages', locale_dir)
        gettext.textdomain('messages')
        _ = gettext.gettext
    except FileNotFoundError:
        gettext.install("messages")  # Fallback to default

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
