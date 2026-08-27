"""RollView's test suite.

Importing the package sandboxes the run: HOME is redirected away from the real
``~/.tapiorqp`` and Qt is pinned to the offscreen platform. Both runners import
this before any test module, which is the point — see ``test/sandbox.py``.
"""

from test import sandbox

sandbox.activate()
