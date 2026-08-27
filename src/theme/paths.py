# Tapio RollView
# Copyright 2024 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Where the system's data files live, running from source or from a bundle.

``tokens.json``, ``rollview.qss`` and the Plex faces are data, not code, so
PyInstaller does not pick them up by following imports — they are listed as
``--add-data`` in the build workflow and land under the extraction root. Asking
for them through here rather than off ``__file__`` is what makes a frozen build
resolve the same paths a source checkout does.

Deliberately free of both Qt and ``settings``: ``theme.tokens`` promises to be
import-safe, and ``utils.preferences`` imports it before ``settings`` is
finished with.
"""

import os
import sys


def root():
    """The directory ``theme/`` and ``assets/`` sit in.

    ``src/`` from a checkout, the PyInstaller extraction root from a bundle.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return bundle
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def theme_file(name):
    """A data file inside the theme package, e.g. ``tokens.json``."""
    return os.path.join(root(), "theme", name)


def asset_dir(*parts):
    """A directory under ``assets``, e.g. ``asset_dir("fonts", "plex")``."""
    return os.path.join(root(), "assets", *parts)
