from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPalette


def view_is_empty(view):
    model_attr = getattr(view, "model", None)
    model = model_attr() if callable(model_attr) else model_attr
    if model is None:
        return False
    return model.rowCount(view.rootIndex()) == 0


def draw_empty_view_text(view, text):
    if not text or not view_is_empty(view):
        return

    painter = QPainter(view.viewport())
    painter.setPen(view.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
    painter.drawText(
        view.viewport().rect().adjusted(12, 0, -12, 0),
        Qt.AlignmentFlag.AlignCenter,
        text,
    )
