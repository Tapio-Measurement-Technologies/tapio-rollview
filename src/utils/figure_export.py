"""Clipboard utilities for copying figures to clipboard."""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QRect
from io import BytesIO
from gui.widgets.ProfileWidget import ProfileWidget
from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget
import settings

def export_figure_with_annotations(
        figure,
        canvas,
        annotation_callback=None,
        dpi=settings.PLOT_IMAGE_EXPORT_DPI,
        scale_multiplier=settings.PLOT_IMAGE_EXPORT_SCALE
):
    """Export a matplotlib figure to buffer with optional annotations.

    Args:
        figure: The matplotlib Figure object
        canvas: The FigureCanvas widget
        annotation_callback: Optional function that draws annotations and returns list of added text objects
        dpi: DPI for rendering (default: 300)
        scale_multiplier: Factor to increase figure size (default: 1)

    Returns:
        BytesIO buffer containing PNG data
    """
    # Save current DPI and size
    original_dpi = figure.dpi
    original_size = figure.get_size_inches()
    added_texts = []

    try:
        # Increase figure size and render at high DPI for better quality
        figure.set_dpi(dpi)
        figure.set_size_inches(
            original_size[0] * scale_multiplier,
            original_size[1] * scale_multiplier
        )

        # Draw annotations if callback provided
        if annotation_callback:
            added_texts = annotation_callback() or []

        # Render to buffer at high DPI
        buffer = BytesIO()
        figure.savefig(buffer, format='png', dpi=dpi, bbox_inches='tight')
        buffer.seek(0)

        return buffer

    finally:
        # Remove annotations
        for text in added_texts:
            text.remove()

        # Always restore original DPI and size
        figure.set_dpi(original_dpi)
        figure.set_size_inches(original_size[0], original_size[1])
        canvas.draw()


def _buffer_to_clipboard(buffer):
    """Copy a PNG buffer to clipboard.

    Args:
        buffer: BytesIO buffer containing PNG data
    """
    image = QImage()
    image.loadFromData(buffer.read(), format='PNG')
    buffer.close()

    clipboard = QApplication.clipboard()
    clipboard.setImage(image)


def _widget_to_clipboard(widget):
    """Copy the rendered widget appearance to clipboard."""
    if isinstance(widget, ProfileWidget):
        included_widgets = [widget.stats_widget, widget.warning_label, widget.canvas]
        capture_rect = QRect()
        for child in included_widgets:
            capture_rect = capture_rect.united(child.geometry())
        pixmap = widget.grab(capture_rect)
    else:
        pixmap = widget.grab()
    clipboard = QApplication.clipboard()
    clipboard.setPixmap(pixmap)


def copy_plot_widget_to_clipboard(
        widget,
        dpi=settings.PLOT_IMAGE_EXPORT_DPI,
        scale_multiplier=settings.PLOT_IMAGE_EXPORT_SCALE
):
    """Copy a plot widget (ProfileWidget or StatisticsAnalysisWidget) to clipboard at high DPI.

    Args:
        widget: The ProfileWidget or StatisticsAnalysisWidget instance
    """
    try:
        if not isinstance(widget, (ProfileWidget, StatisticsAnalysisWidget)):
            print(f"Unsupported widget type for clipboard copy: {type(widget)}")
            return

        _widget_to_clipboard(widget)
        print("Plot copied to clipboard.")

    except Exception as e:
        print(f"Error copying plot to clipboard: {e}")
