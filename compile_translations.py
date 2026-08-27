"""Compile ``translations/*.po`` into ``src/locales/**/messages.mo``.

The catalogs are generated, untracked build output; run this after editing a
``.po`` file. Running the app or the test suite from a checkout compiles them
automatically (see ``utils.po_compile``), so this is mainly for build steps and
for regenerating by hand.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from utils import po_compile  # noqa: E402


if __name__ == "__main__":
    po_compile.compile_all(verbose=True)
