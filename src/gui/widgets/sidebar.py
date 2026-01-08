from PySide6.QtWidgets import QVBoxLayout, QFrame, QSplitter
from PySide6.QtCore import Qt

class Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("Sidebar { background-color: palette(window); }")

        # Use a vertical layout to contain the main splitter
        self.setLayout(QVBoxLayout(self))

        # Create the main splitter that will contain all widgets
        self.main_splitter = QSplitter()
        self.main_splitter.setOrientation(Qt.Orientation.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(1)

        # Add the splitter to the layout
        self.layout().addWidget(self.main_splitter)

        self.widgets = []

    def addWidget(self, widget, size=None):
        self.widgets.append(widget)
        self.main_splitter.addWidget(widget)

        # Configure initial size if specified
        if size is not None:
            # Get current splitter sizes
            current_sizes = self.main_splitter.sizes()

            # If this is the first widget, set its size directly
            if len(current_sizes) == 1:
                self.main_splitter.setSizes([size])
            else:
                # For subsequent widgets, adjust the sizes to accommodate the new widget
                # We'll distribute the remaining space proportionally among existing widgets
                total_size = sum(current_sizes)
                remaining_size = total_size - size

                if remaining_size > 0:
                    # Calculate proportional sizes for existing widgets
                    new_sizes = []
                    for i, current_size in enumerate(current_sizes[:-1]):  # Exclude the last widget (the new one)
                        proportion = current_size / (total_size - current_sizes[-1])
                        new_sizes.append(int(remaining_size * proportion))

                    # Add the new widget's size
                    new_sizes.append(size)

                    # Set the new sizes
                    self.main_splitter.setSizes(new_sizes)

    def setWidgetSizes(self, sizes):
        """
        Set sizes for all widgets in the sidebar.

        Args:
            sizes (list): List of integers representing the size for each widget.
                         The length should match the number of widgets.
        """
        if len(sizes) == len(self.widgets):
            self.main_splitter.setSizes(sizes)
        else:
            raise ValueError(f"Expected {len(self.widgets)} sizes, got {len(sizes)}")

    def getWidgetSizes(self):
        """
        Get current sizes of all widgets in the sidebar.

        Returns:
            list: List of integers representing current widget sizes.
        """
        return self.main_splitter.sizes()