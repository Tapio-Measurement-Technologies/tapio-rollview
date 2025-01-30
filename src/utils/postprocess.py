from PySide6.QtCore import QThread, Signal
from gui.widgets.messagebox import show_info_msgbox, show_warn_msgbox
from gui.widgets.ProgressBarDialog import ProgressBarDialog
from utils.dynamic_loader import load_modules_from_folder
from utils.translation import _
from utils import preferences
import os

thread = None
base_path = os.path.dirname(os.path.abspath(__file__))
postprocessors = load_modules_from_folder(os.path.abspath(
    os.path.join(base_path, os.pardir, 'postprocessors')))

for module_name, postprocessor in postprocessors.items():
    postprocessor.enabled = module_name in preferences.enabled_postprocessors

class PostprocessThread(QThread):
    now_processing = Signal(str, str)  # folder name, postprocessor name
    folder_processed = Signal(str)  # folder name
    processing_failed = Signal(str)  # folder name

    def __init__(self, folder_paths):
        super().__init__()
        self.folder_paths = folder_paths

    def run(self):
        if not self.folder_paths:
            return
        for folder_path in self.folder_paths:
            for module_name, postprocessor in postprocessors.items():
                postprocessor_name = getattr(
                    postprocessor, 'description', module_name)
                if postprocessor.enabled:
                    self.now_processing.emit(folder_path, postprocessor_name)
                    print(f"Running postprocessor '{
                          postprocessor_name}' for folder '{folder_path}'...")
                    try:
                        if postprocessor.run(folder_path):
                            self.folder_processed.emit(folder_path)
                        else:
                            self.processing_failed.emit(folder_path)
                    except Exception as e:
                        print(f"Error in postprocessor '{
                              postprocessor_name}': {e}")
                        self.processing_failed.emit(folder_path)


def get_postprocessors():
    return postprocessors


def toggle_postprocessor(postprocessor_module):
    postprocessor_module.enabled = not postprocessor_module.enabled
    if postprocessor_module.enabled:
        print(f"Enabled postprocessor '{postprocessor_module.description}'")
    else:
        print(f"Disabled postprocessor '{postprocessor_module.description}'")
    enabled_postprocessors = [
        module_name
        for module_name, postprocessor in postprocessors.items()
        if postprocessor.enabled
    ]
    preferences.update_enabled_postprocessors(enabled_postprocessors)


def run_postprocessors(folder_paths):
    global thread
    thread = PostprocessThread(folder_paths)
    error_paths = set()
    dialog = ProgressBarDialog(auto_close=True)
    enabled_postprocessors = [
        postprocessor for postprocessor in postprocessors.values() if postprocessor.enabled]
    total_items_to_process = len(folder_paths) * len(enabled_postprocessors)
    processed_items = 0

    def on_postprocess_fail(folder_path):
        error_paths.add(folder_path)

    def on_now_processing(folder_path, postprocessor_name):
        nonlocal processed_items
        processed_items += 1
        dialog.update_progress((processed_items / total_items_to_process) *
                               100, f"{_("POSTPROCESSORS_DIALOG_RUNNING_TEXT")}:\n{folder_path}\n{postprocessor_name}")

    def on_finished():
        dialog.update_progress(100, _("POSTPROCESSORS_DIALOG_FINISHED_TEXT"))
        if error_paths:
            show_warn_msgbox(
                f"{_("POSTPROCESSORS_ERROR_TEXT")}:\n\n{'\n'.join(error_paths)}")
        else:
            show_info_msgbox(_("POSTPROCESSORS_SUCCESS_TEXT"), "Success")

    thread.now_processing.connect(on_now_processing)
    thread.processing_failed.connect(on_postprocess_fail)
    thread.finished.connect(on_finished)

    dialog.show()
    thread.start()
