# Tapio RollView
# Copyright 2026 Tapio Measurement Technologies Oy

# Tapio RollView is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.


from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from utils import preferences
from utils.translation import _
import math
import qrcode

# QR code display dimensions in pixels
QR_CODE_SIZE_PX = 300

class QRConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("QR_CONFIG_DIALOG_TITLE"))
        self.setModal(True)
        self.setFixedSize(620, 340)

        main_layout = QVBoxLayout()

        content_layout = QHBoxLayout()
        instructions_layout = QVBoxLayout()

        # Instruction label
        instruction_label = QLabel(_("QR_CONFIG_INSTRUCTION"))
        instruction_label.setWordWrap(True)
        instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        instructions_layout.addWidget(instruction_label)

        # Alert limits display label
        self.limits_label = QLabel()
        self.limits_label.setWordWrap(True)
        self.limits_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.limits_label.setStyleSheet("font-family: monospace; padding: 10px; background-color: #f0f0f0;")
        instructions_layout.addWidget(self.limits_label)

        content_layout.addLayout(instructions_layout)

        # QR code label
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.qr_label)

        main_layout.addLayout(content_layout)

        # Close button
        close_button = QPushButton(_("BUTTON_TEXT_CLOSE"))
        close_button.clicked.connect(self.accept)
        main_layout.addWidget(close_button)

        self.setLayout(main_layout)

        # Generate and display QR code
        self.generate_qr_code()

    def format_value(self, value):
        """Format a value for the config string, converting None to NaN."""
        if value is None:
            return "NaN"
        # Check if value is NaN (for float type)
        if isinstance(value, float) and math.isnan(value):
            return "NaN"
        return str(value)

    def generate_config_string(self):
        """Generate the configuration string from preferences."""
        alert_limits = preferences.alert_limits

        # Create a mapping of stat names to their min/max values
        limits_map = {}
        for limit in alert_limits:
            name = limit.get('name', '')
            limits_map[name] = {
                'min': limit.get('min'),
                'max': limit.get('max')
            }

        # Build the config string in the specified format
        # Format: \x01CFG:mean_g_min=1;mean_g_max=1;stdev_g_min=1;stdev_g_max=NaN;...
        config_parts = []

        # Order of parameters as specified in the example
        stat_names = ['mean_g', 'stdev_g', 'cv_prcnt', 'min_g', 'max_g', 'pp_g']

        for stat_name in stat_names:
            # Handle cv_pct -> cv_prcnt mapping
            lookup_name = 'cv_pct' if stat_name == 'cv_prcnt' else stat_name

            limits = limits_map.get(lookup_name, {'min': None, 'max': None})
            config_parts.append(f"{stat_name}_min={self.format_value(limits['min'])}")
            config_parts.append(f"{stat_name}_max={self.format_value(limits['max'])}")

        config_string = "\x01CFG:" + ";".join(config_parts)
        return config_string

    def generate_limits_display(self):
        """Generate a human-readable display of alert limits."""
        alert_limits = preferences.alert_limits

        # Create a mapping of stat names to their min/max values and units
        limits_map = {}
        for limit in alert_limits:
            name = limit.get('name', '')
            limits_map[name] = {
                'min': limit.get('min'),
                'max': limit.get('max'),
                'units': limit.get('units', '')
            }

        # Display names mapping
        display_names = {
            'mean_g': _('ALERT_LIMIT_MEAN'),
            'stdev_g': _('ALERT_LIMIT_STDEV'),
            'cv_pct': _('ALERT_LIMIT_CV'),
            'min_g': _('ALERT_LIMIT_MIN'),
            'max_g': _('ALERT_LIMIT_MAX'),
            'pp_g': _('ALERT_LIMIT_PP')
        }

        # Find the longest display name for alignment
        max_name_length = max(len(display_names[name]) for name in display_names)

        lines = []
        for stat_name in ['mean_g', 'stdev_g', 'cv_pct', 'min_g', 'max_g', 'pp_g']:
            limits = limits_map.get(stat_name, {'min': None, 'max': None, 'units': ''})
            display_name = display_names.get(stat_name, stat_name)
            min_val = self.format_value(limits['min'])
            max_val = self.format_value(limits['max'])
            units = limits['units']
            # Left-align name, right-align values with padding, add units
            lines.append(f"{display_name:<{max_name_length}}  {min_val:>8} - {max_val:<8} {units}")

        return "\n".join(lines)

    def generate_qr_code(self):
        """Generate QR code from config string."""
        try:
            config_string = self.generate_config_string()

            # Display alert limits
            limits_text = self.generate_limits_display()
            self.limits_label.setText(limits_text)

            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(config_string)
            qr.make(fit=True)

            # Create an image from the QR Code
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert PIL Image to QPixmap
            img = img.convert("RGB")
            data = img.tobytes("raw", "RGB")
            # Calculate the bytes per line (stride) - must be width * 3 for RGB
            bytes_per_line = img.size[0] * 3
            qimage = QImage(data, img.size[0], img.size[1], bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)

            # Scale to constant size
            scaled_pixmap = pixmap.scaled(QR_CODE_SIZE_PX, QR_CODE_SIZE_PX,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)

            # Display the QR code
            self.qr_label.setPixmap(scaled_pixmap)

        except Exception as e:
            # Show any other error
            error_label = QLabel(f"{_('ERROR_MSGBOX_TITLE')}: {str(e)}")
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: red;")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.qr_label.setParent(None)
            self.layout().addWidget(error_label)
