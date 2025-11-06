"""Clipboard utilities for copying widgets and figures to clipboard."""

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QImage, QPixmap, QPainter
from io import BytesIO


class Screenshottable:
    """Mixin class for widgets that can be copied to clipboard with custom logic.

    Usage: Inherit from this class and override get_screenshot_widgets() to specify
    which child widgets should be included in screenshots.
    """

    def get_screenshot_widgets(self):
        """Override this method to return a list of widgets to include in screenshots.

        Returns:
            List of QWidget objects to capture, or None to capture entire widget
        """
        return None

    def copy_to_clipboard(self):
        """Copy this widget to clipboard based on screenshot configuration."""
        copy_widget_to_clipboard(self)


def copy_widget_to_clipboard(widget: QWidget):
    """Copies a Qt widget to clipboard as an image.

    If widget is Screenshottable and has screenshot widgets configured,
    only those specific widgets will be captured. Otherwise captures entire widget.

    Args:
        widget: The QWidget to copy to clipboard
    """
    try:
        if isinstance(widget, Screenshottable):
            widgets = widget.get_screenshot_widgets()
            if widgets:
                pixmap = _capture_widgets(widgets)
            else:
                pixmap = widget.grab()
        else:
            pixmap = widget.grab()

        # Convert to QImage and copy to clipboard
        image = pixmap.toImage()
        clipboard = QApplication.clipboard()
        clipboard.setImage(image)
        print("Widget copied to clipboard.")
    except Exception as e:
        print(f"Error copying widget to clipboard: {e}")


def _capture_widgets(widgets: list) -> QPixmap:
    """Capture multiple widgets and combine them into a single pixmap.

    Args:
        widgets: List of QWidget objects to capture

    Returns:
        QPixmap containing all widgets stacked vertically
    """
    total_height = 0
    max_width = 0

    captures = []
    for widget in widgets:
        if widget.isVisible():
            pixmap = widget.grab()
            captures.append(pixmap)
            total_height += pixmap.height()
            max_width = max(max_width, pixmap.width())

    if not captures:
        return QPixmap()

    # Create combined pixmap
    combined = QPixmap(max_width, total_height)
    combined.fill()  # Fill with white background

    painter = QPainter(combined)
    y_offset = 0

    for pixmap in captures:
        painter.drawPixmap(0, y_offset, pixmap)
        y_offset += pixmap.height()

    painter.end()

    return combined


def copy_figure_to_clipboard(figure):
    """Copies a matplotlib figure to the clipboard as a PNG image.

    Args:
        figure: The matplotlib Figure object to copy
    """
    try:
        buffer = BytesIO()
        figure.savefig(buffer, format='png', dpi=300)
        buffer.seek(0)

        # Convert buffer to QImage
        image = QImage()
        image.loadFromData(buffer.read(), format='PNG')
        buffer.close()

        # Copy to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setImage(image)
        print("Figure copied to clipboard.")
    except Exception as e:
        print(f"Error copying figure to clipboard: {e}")
