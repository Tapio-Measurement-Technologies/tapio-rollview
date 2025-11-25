"""Clipboard utilities for copying figures to clipboard."""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from io import BytesIO
from gui.widgets.chart import Chart
from gui.widgets.StatisticsAnalysis import StatisticsAnalysisWidget


def export_figure_with_annotations(figure, canvas, annotation_callback=None, dpi=300, scale_multiplier=1):
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


def copy_plot_widget_to_clipboard(widget, dpi=300, scale_multiplier=1):
    """Copy a plot widget (Chart or StatisticsAnalysisWidget) to clipboard at high DPI.

    Args:
        widget: The Chart or StatisticsAnalysisWidget instance
    """
    try:
        if isinstance(widget, Chart):
            figure = widget.figure
            canvas = widget.canvas
            annotation_callback = widget._draw_stats_on_figure
        elif isinstance(widget, StatisticsAnalysisWidget):
            figure = widget.chart.figure
            canvas = widget.chart.canvas
            annotation_callback = widget.chart._draw_info_on_figure
        else:
            print(f"Unsupported widget type for clipboard copy: {type(widget)}")
            return

        buffer = export_figure_with_annotations(
                figure=figure,
                canvas=canvas,
                annotation_callback=annotation_callback,
                dpi=dpi,
                scale_multiplier=scale_multiplier
        )
        _buffer_to_clipboard(buffer)
        print("Plot copied to clipboard.")

    except Exception as e:
        print(f"Error copying plot to clipboard: {e}")
