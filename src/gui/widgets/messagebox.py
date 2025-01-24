from PySide6.QtWidgets import QMessageBox
from gettext import gettext as _

def show_info_msgbox(text: str, title: str, buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok):
    show_message_box(text, title, QMessageBox.Icon.Information, buttons)

def show_error_msgbox(text: str, title: str = _("ERROR_MSGBOX_TITLE"), buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok):
    show_message_box(text, title, QMessageBox.Icon.Critical, buttons)

def show_warn_msgbox(text: str, title: str = _("WARNING_MSGBOX_TITLE"), buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok):
    show_message_box(text, title, QMessageBox.Icon.Warning, buttons)

def show_message_box(text: str, title: str, icon: QMessageBox.Icon, buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok):
    # Create a message box
    msg_box = QMessageBox()

    # Set the title of the message box
    msg_box.setWindowTitle(title)

    # Set the message box text
    msg_box.setText(text)

    # Set the icon for the message box (optional)
    msg_box.setIcon(icon)

    # Add standard buttons (OK button in this case)
    msg_box.setStandardButtons(buttons)

    # Execute the message box (this makes it appear)
    msg_box.exec()