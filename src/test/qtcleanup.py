"""Destroying Qt widgets properly in a test.

``close()`` only hides a widget; the C++ object lives on until something deletes
it. Leaving a tree of them for the garbage collector to unpick later leaks the
tree at best and ends in a double free at worst — Python and Qt both believe
they own the children. The ``main_window`` fixture in ``conftest.py`` does this
dance already; this is the same thing for tests that build a widget directly.
"""

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop


def destroy(widget):
    """Close, unparent, delete and drain, so nothing survives the test."""
    widget.close()
    widget.setParent(None)
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
