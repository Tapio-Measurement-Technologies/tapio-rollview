class ZoomPan:
    def __init__(self, fig):
        self.fig = fig
        self.press = None
        self.cur_xlim = None
        self.cur_ylim = None
        self.x0 = None
        self.y0 = None
        self.x1 = None
        self.y1 = None
        self.xpress = None
        self.ypress = None
        self.current_pan_ax = None


    def zoom_factory(self, base_scale=2.):
        def zoom(event):
            # Determine which axis the cursor is over
            if event.inaxes is None:
                return

            target_ax = event.inaxes

            cur_xlim = target_ax.get_xlim()
            cur_ylim = target_ax.get_ylim()

            xdata = event.xdata  # get event x location
            ydata = event.ydata  # get event y location

            if event.button == 'up':
                scale_factor = 1 / base_scale  # Zoom in
            elif event.button == 'down':
                scale_factor = base_scale  # Zoom out
            else:
                scale_factor = 1  # Do nothing

            new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
            new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor

            relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
            rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])

            target_ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
            target_ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
            target_ax.figure.canvas.draw()

        self.fig.canvas.mpl_connect('scroll_event', zoom)

        return zoom

    def pan_factory(self):
        def onPress(event):
            # Check if toolbar is in zoom or pan mode
            toolbar = self.fig.canvas.toolbar
            if toolbar is not None and toolbar.mode in ['pan/zoom', 'zoom rect']:
                return  # Ignore if in zoom or pan mode

            if event.inaxes is None:
                return

            # Store which axis we're panning
            self.current_pan_ax = event.inaxes
            self.cur_xlim = self.current_pan_ax.get_xlim()
            self.cur_ylim = self.current_pan_ax.get_ylim()
            self.press = self.x0, self.y0, event.xdata, event.ydata
            self.x0, self.y0, self.xpress, self.ypress = self.press

        def onRelease(event):
            self.press = None
            self.current_pan_ax = None
            self.fig.canvas.draw()

        def onMotion(event):
            # Check if toolbar is in zoom or pan mode
            toolbar = self.fig.canvas.toolbar
            if toolbar is not None and toolbar.mode in ['pan/zoom', 'zoom rect']:
                return  # Ignore if in zoom or pan mode

            if self.press is None or self.current_pan_ax is None:
                return
            if event.inaxes != self.current_pan_ax:
                return
            dx = event.xdata - self.xpress
            dy = event.ydata - self.ypress
            self.cur_xlim -= dx
            self.cur_ylim -= dy
            self.current_pan_ax.set_xlim(self.cur_xlim)
            self.current_pan_ax.set_ylim(self.cur_ylim)

            self.current_pan_ax.figure.canvas.draw_idle()

        # Attach the callbacks
        self.fig.canvas.mpl_connect('button_press_event', onPress)
        self.fig.canvas.mpl_connect('button_release_event', onRelease)
        self.fig.canvas.mpl_connect('motion_notify_event', onMotion)

        return onMotion