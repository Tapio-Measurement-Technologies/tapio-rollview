from PySide6 import QtCore, QtGui, QtWidgets

# Originated from
# https://www.mail-archive.com/pyqt@riverbankcomputing.com/msg22889.html
# Modification refered from
# https://gist.github.com/Riateche/27e36977f7d5ea72cf4f

class RangeSlider(QtWidgets.QSlider):
    sliderMoved = QtCore.Signal(float, float)

    """ A slider for ranges.

        This class provides a dual-slider for ranges, where there is a defined
        maximum and minimum, as is a normal slider, but instead of having a
        single slider value, there are 2 slider values.

        This class emits the same signals as the QSlider base class, with the
        exception of valueChanged
    """
    def __init__(self, *args):
        super(RangeSlider, self).__init__(*args)

        self._minimum = 0.0
        self._maximum = 100.0
        self._low = 0.0
        self._high = 100.0
        self._step = 1.0  # Default step for double precision

        self.pressed_control = QtWidgets.QStyle.SubControl.SC_None
        self.tick_interval = 0
        self.tick_position = QtWidgets.QSlider.TickPosition.NoTicks
        self.hover_control = QtWidgets.QStyle.SubControl.SC_None
        self.click_offset = 0

        # 0 for the low, 1 for the high, -1 for both
        self.active_slider = 0

        # Set up internal slider range (use a large range for precision)
        super().setMinimum(0)
        super().setMaximum(10000)

        # Create editable labels for handle values
        self.low_label = QtWidgets.QLineEdit(self)
        self.low_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.low_label.setFixedWidth(40)
        self.low_label.setFixedHeight(22)
        self.low_label.returnPressed.connect(self._on_low_label_changed)
        self.low_label.editingFinished.connect(self._update_low_label_text)
        self.low_label.setStyleSheet("QLineEdit { background: transparent; border: none; }")

        self.high_label = QtWidgets.QLineEdit(self)
        self.high_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.high_label.setFixedWidth(40)
        self.high_label.setFixedHeight(22)
        self.high_label.returnPressed.connect(self._on_high_label_changed)
        self.high_label.editingFinished.connect(self._update_high_label_text)
        self.high_label.setStyleSheet("QLineEdit { background: transparent; border: none; }")

        # Ensure minimum height for the slider to accommodate labels
        self.setMinimumHeight(50)

        # Initialize label text and positions
        self._update_low_label_text()
        self._update_high_label_text()

        # Raise labels to be on top
        self.low_label.raise_()
        self.high_label.raise_()

    def setMinimum(self, value: float):
        """Set the minimum value for the slider."""
        self._minimum = float(value)
        if self._low < self._minimum:
            self._low = self._minimum
        self.update()

    def setMaximum(self, value: float):
        """Set the maximum value for the slider."""
        self._maximum = float(value)
        if self._high > self._maximum:
            self._high = self._maximum
        self.update()

    def minimum(self):
        """Get the minimum value for the slider."""
        return self._minimum

    def maximum(self):
        """Get the maximum value for the slider."""
        return self._maximum

    def low(self):
        return self._low

    def setLow(self, low: float):
        self._low = float(low)
        self._update_low_label_text()
        self._update_label_positions()
        self.update()

    def high(self):
        return self._high

    def setHigh(self, high: float):
        self._high = float(high)
        self._update_high_label_text()
        self._update_label_positions()
        self.update()

    def setSingleStep(self, step: float):
        """Set the step size for the slider (for double precision)."""
        self._step = float(step)

    def singleStep(self):
        """Get the step size for the slider."""
        return self._step

    def _format_value(self, value):
        """Format value for display in label."""
        if self._step >= 1:
            return f"{int(value)}"
        else:
            # Determine decimal places based on step size
            decimal_places = len(str(self._step).split('.')[-1]) if '.' in str(self._step) else 0
            return f"{value:.{decimal_places}f}"

    def _update_low_label_text(self):
        """Update the low label text to show current value."""
        if not self.low_label.hasFocus():
            self.low_label.setText(self._format_value(self._low))

    def _update_high_label_text(self):
        """Update the high label text to show current value."""
        if not self.high_label.hasFocus():
            self.high_label.setText(self._format_value(self._high))

    def _on_low_label_changed(self):
        """Handle when user edits the low label."""
        try:
            value = float(self.low_label.text())
            value = max(self._minimum, min(value, self._high - self._step))
            # Round to step precision
            if self._step > 0:
                value = round(value / self._step) * self._step
            self._low = value
            self.update()
            self.sliderMoved.emit(self._low, self._high)
        except ValueError:
            pass
        self._update_low_label_text()
        self._update_label_positions()

    def _on_high_label_changed(self):
        """Handle when user edits the high label."""
        try:
            value = float(self.high_label.text())
            value = max(self._low + self._step, min(value, self._maximum))
            # Round to step precision
            if self._step > 0:
                value = round(value / self._step) * self._step
            self._high = value
            self.update()
            self.sliderMoved.emit(self._low, self._high)
        except ValueError:
            pass
        self._update_high_label_text()
        self._update_label_positions()

    def _update_label_positions(self):
        """Update the position of the labels to be above their handles."""
        if not self.isVisible():
            return

        style = self.style()
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)

        # Get low handle position
        opt.sliderPosition = int(self._value_to_position(self._low))
        low_rect = style.subControlRect(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, QtWidgets.QStyle.SubControl.SC_SliderHandle, self)

        # Get high handle position
        opt.sliderPosition = int(self._value_to_position(self._high))
        high_rect = style.subControlRect(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, QtWidgets.QStyle.SubControl.SC_SliderHandle, self)

        # Position labels above handles
        # Use a small offset from the top of the widget
        label_y = -4  # Small margin from top

        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            # Calculate label x positions centered on handles
            low_x = low_rect.center().x() - self.low_label.width() // 2
            high_x = high_rect.center().x() - self.high_label.width() // 2

            # Clamp positions to stay within widget bounds
            low_x = max(0, min(low_x, self.width() - self.low_label.width()))
            high_x = max(0, min(high_x, self.width() - self.high_label.width()))

            self.low_label.move(low_x, label_y)
            self.high_label.move(high_x, label_y)
            self.low_label.show()
            self.high_label.show()
        else:
            # For vertical sliders (not commonly used, but implemented for completeness)
            label_x = 2
            self.low_label.move(label_x, low_rect.center().y() - self.low_label.height() // 2)
            self.high_label.move(label_x, high_rect.center().y() - self.high_label.height() // 2)
            self.low_label.show()
            self.high_label.show()

    def paintEvent(self, event):
        # based on http://qt.gitorious.org/qt/qt/blobs/master/src/gui/widgets/qslider.cpp

        painter = QtGui.QPainter(self)

        # FIXED: use self.style(), not QApplication.style() by MaurizioB
        # style = QtWidgets.QApplication.style()
        style = self.style()

        # draw groove
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        opt.siderValue = 0
        opt.sliderPosition = 0
        opt.subControls = QtWidgets.QStyle.SubControl.SC_SliderGroove
        if self.tickPosition() != QtWidgets.QSlider.TickPosition.NoTicks: #self.NoTicks:
            opt.subControls |= QtWidgets.QStyle.SubControl.SC_SliderTickmarks
        style.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, painter, self)
        groove = style.subControlRect(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, QtWidgets.QStyle.SubControl.SC_SliderGroove, self)

        # drawSpan
        #opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        opt.subControls = QtWidgets.QStyle.SubControl.SC_SliderGroove
        #if self.tickPosition() != self.NoTicks:
        #    opt.subControls |= QtWidgets.QStyle.SubControl.SC_SliderTickmarks
        opt.siderValue = 0
        #print(self._low)
        opt.sliderPosition = int(self._value_to_position(self._low))
        low_rect = style.subControlRect(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, QtWidgets.QStyle.SubControl.SC_SliderHandle, self)
        opt.sliderPosition = int(self._value_to_position(self._high))
        high_rect = style.subControlRect(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, QtWidgets.QStyle.SubControl.SC_SliderHandle, self)

        #print(low_rect, high_rect)
        low_pos = self.__pick(low_rect.center())
        high_pos = self.__pick(high_rect.center())

        min_pos = min(low_pos, high_pos)
        max_pos = max(low_pos, high_pos)

        c = QtCore.QRect(low_rect.center(), high_rect.center()).center()
        #print(min_pos, max_pos, c)
        if opt.orientation == QtCore.Qt.Orientation.Horizontal:
            span_rect = QtCore.QRect(QtCore.QPoint(min_pos, c.y()-2), QtCore.QPoint(max_pos, c.y()+1))
        else:
            span_rect = QtCore.QRect(QtCore.QPoint(c.x()-2, min_pos), QtCore.QPoint(c.x()+1, max_pos))

        #self.initStyleOption(opt)
        #print(groove.x(), groove.y(), groove.width(), groove.height())
        if opt.orientation == QtCore.Qt.Orientation.Horizontal: groove.adjust(0, 0, -1, 0)
        else: groove.adjust(0, 0, 0, -1)

        if True: #self.isEnabled():
            highlight = self.palette().color(QtGui.QPalette.ColorRole.Highlight)
            painter.setBrush(QtGui.QBrush(highlight))
            painter.setPen(QtGui.QPen(highlight, 0))
            #painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.Dark), 0))
            '''
            if opt.orientation == QtCore.Qt.Horizontal:
                self.setupPainter(painter, opt.orientation, groove.center().x(), groove.top(), groove.center().x(), groove.bottom())
            else:
                self.setupPainter(painter, opt.orientation, groove.left(), groove.center().y(), groove.right(), groove.center().y())
            '''
            #spanRect =
            painter.drawRect(span_rect.intersected(groove))
            #painter.drawRect(groove)

        for i, value in enumerate([self._low, self._high]):
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)

            # Only draw the groove for the first slider so it doesn't get drawn
            # on top of the existing ones every time
            if i == 0:
                opt.subControls = QtWidgets.QStyle.SubControl.SC_SliderHandle# | QtWidgets.QStyle.SubControl.SC_SliderGroove
            else:
                opt.subControls = QtWidgets.QStyle.SubControl.SC_SliderHandle

            if self.tickPosition() != QtWidgets.QSlider.TickPosition.NoTicks: #self.NoTicks:
                opt.subControls |= QtWidgets.QStyle.SubControl.SC_SliderTickmarks

            if self.pressed_control:
                opt.activeSubControls = self.pressed_control
            else:
                opt.activeSubControls = self.hover_control

            opt.sliderPosition = int(self._value_to_position(value))
            opt.sliderValue = int(self._value_to_position(value))
            style.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_Slider, opt, painter, self)

    def mousePressEvent(self, event):
        event.accept()

        style = QtWidgets.QApplication.style()
        button = event.button()

        # In a normal slider control, when the user clicks on a point in the
        # slider's total range, but not on the slider part of the control the
        # control would jump the slider value to where the user clicked.
        # For this control, clicks which are not direct hits will slide both
        # slider parts

        if button:
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)

            self.active_slider = -1

            for i, value in enumerate([self._low, self._high]):
                opt.sliderPosition = int(self._value_to_position(value))
                # hit = style.hitTestComplexControl(style.CC_Slider, opt, event.pos(), self)
                # print(event.pos(), event.position())
                hit = style.hitTestComplexControl(style.ComplexControl.CC_Slider, opt, event.position().toPoint(), self)
                # if hit == style.SC_SliderHandle:
                if hit == style.SubControl.SC_SliderHandle:
                    self.active_slider = i
                    self.pressed_control = hit

                    # self.triggerAction(self.SliderMove)
                    self.triggerAction(self.SliderAction.SliderMove)
                    # self.setRepeatAction(self.SliderNoAction)
                    self.setRepeatAction(self.SliderAction.SliderNoAction)
                    self.setSliderDown(True)
                    break

            if self.active_slider < 0:
                self.pressed_control = QtWidgets.QStyle.SubControl.SC_SliderHandle
                # self.click_offset = self.__pixelPosToRangeValue(self.__pick(event.pos()))
                self.click_offset = self.__pixelPosToRangeValue(self.__pick(event.position().toPoint()))
                # self.triggerAction(self.SliderMove)
                self.triggerAction(self.SliderAction.SliderMove)
                # self.setRepeatAction(self.SliderNoAction)
                self.setRepeatAction(self.SliderAction.SliderNoAction)
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self.pressed_control != QtWidgets.QStyle.SubControl.SC_SliderHandle:
            event.ignore()
            return

        event.accept()
        # new_pos = self.__pixelPosToRangeValue(self.__pick(event.pos()))
        new_pos = self.__pixelPosToRangeValue(self.__pick(event.position().toPoint()))
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)

        if self.active_slider < 0:
            offset = new_pos - self.click_offset
            self._high += offset
            self._low += offset
            if self._low < self._minimum:
                diff = self._minimum - self._low
                self._low += diff
                self._high += diff
            if self._high > self._maximum:
                diff = self._maximum - self._high
                self._low += diff
                self._high += diff
        elif self.active_slider == 0:
            if new_pos >= self._high:
                new_pos = self._high - self._step
            self._low = max(self._minimum, new_pos)
        else:
            if new_pos <= self._low:
                new_pos = self._low + self._step
            self._high = min(self._maximum, new_pos)

        self.click_offset = new_pos

        self.update()
        self._update_low_label_text()
        self._update_high_label_text()
        self._update_label_positions()

        #self.emit(QtCore.SIGNAL('sliderMoved(int)'), new_pos)
        self.sliderMoved.emit(self._low, self._high)

    def resizeEvent(self, event):
        """Handle resize events to reposition labels."""
        super().resizeEvent(event)
        self._update_label_positions()

    def showEvent(self, event):
        """Handle show events to position labels initially."""
        super().showEvent(event)
        self._update_low_label_text()
        self._update_high_label_text()
        self._update_label_positions()

    def _value_to_position(self, value):
        """Convert a float value to an integer position for the underlying QSlider."""
        # Map from [_minimum, _maximum] to [0, 10000]
        if self._maximum == self._minimum:
            return 0
        ratio = (value - self._minimum) / (self._maximum - self._minimum)
        return int(ratio * super().maximum())

    def _position_to_value(self, position):
        """Convert an integer position from QSlider to a float value."""
        # Map from [0, 10000] to [_minimum, _maximum]
        ratio = position / super().maximum()
        value = self._minimum + ratio * (self._maximum - self._minimum)
        # Round to step precision
        if self._step > 0:
            value = round(value / self._step) * self._step
        return value

    def __pick(self, pt):
        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            return pt.x()
        else:
            return pt.y()


    def __pixelPosToRangeValue(self, pos):
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        style = QtWidgets.QApplication.style()

        # gr = style.subControlRect(style.CC_Slider, opt, style.SC_SliderGroove, self)
        gr = style.subControlRect(style.ComplexControl.CC_Slider, opt, style.SubControl.SC_SliderGroove, self)
        # sr = style.subControlRect(style.CC_Slider, opt, style.SC_SliderHandle, self)
        sr = style.subControlRect(style.ComplexControl.CC_Slider, opt, style.SubControl.SC_SliderHandle, self)

        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            slider_length = sr.width()
            slider_min = gr.x()
            slider_max = gr.right() - slider_length + 1
        else:
            slider_length = sr.height()
            slider_min = gr.y()
            slider_max = gr.bottom() - slider_length + 1

        int_position = style.sliderValueFromPosition(super().minimum(), super().maximum(),
                                             pos-slider_min, slider_max-slider_min,
                                             opt.upsideDown)
        return self._position_to_value(int_position)

