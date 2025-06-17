from PySide6.QtCore import QThread, Signal, QObject
from gui.widgets.ProgressBarDialog import ProgressBarDialog
from utils.dynamic_loader import load_modules_from_folder
from utils.translation import _
from utils import preferences
from dataclasses import dataclass, field
import os
import settings

thread = None
base_path = os.path.dirname(os.path.abspath(__file__))
postprocessors = {}

# Load built-in postprocessors
builtin_postprocessors_path = os.path.abspath(
    os.path.join(base_path, os.pardir, 'postprocessors'))
if os.path.exists(builtin_postprocessors_path):
    postprocessors.update(load_modules_from_folder(builtin_postprocessors_path))

# Load user postprocessors
user_postprocessors_path = os.path.join(settings.ROOT_DIRECTORY, 'postprocessors')
if os.path.exists(user_postprocessors_path):
    print("Loading user postprocessors")
    postprocessors.update(load_modules_from_folder(user_postprocessors_path))

for module_name, postprocessor in postprocessors.items():
    postprocessor.enabled = module_name in preferences.enabled_postprocessors


class PostprocessThread(QThread):
    now_processing = Signal(str, str)  # folder name, postprocessor name
    processing_successful = Signal(str)  # folder name
    processing_failed = Signal(str)  # folder name
    processing_cancelled = Signal()

    def __init__(self, folder_paths):
        super().__init__()
        self.folder_paths = folder_paths
        self._is_cancellation_requested = False

    def request_cancellation(self):
        self._is_cancellation_requested = True

    def run(self):
        if not self.folder_paths:
            return
        for folder_path in self.folder_paths:
            if self._is_cancellation_requested:
                self.processing_cancelled.emit()
                return
            for module_name, postprocessor in postprocessors.items():
                if self._is_cancellation_requested:
                    self.processing_cancelled.emit()
                    return

                postprocessor_name = getattr(
                    postprocessor, 'description', module_name)
                if postprocessor.enabled:
                    self.now_processing.emit(folder_path, postprocessor_name)
                    print(f"Running postprocessor '{
                          postprocessor_name}' for folder '{folder_path}'...")
                    try:
                        if postprocessor.run(folder_path):
                            self.processing_successful.emit(folder_path)
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

@dataclass(frozen=True)
class PostprocessResult:
    processed_folders: list[str] = field(default_factory=list)
    failed_folders: list[str] = field(default_factory=list)

class PostprocessManager(QObject):
    postprocess_finished = Signal(PostprocessResult)

    def __init__(self):
        super().__init__()
        self._thread = None
        self.dialog = None
        self.error_paths = set()
        self.success_paths = set()
        self.enabled_postprocessors = [postprocessor for postprocessor in postprocessors.values() if postprocessor.enabled]
        self.total_items_to_process = 0

    def run_postprocessors(self, folder_paths):
        self._thread = PostprocessThread(folder_paths)
        self.error_paths = set()
        self.dialog = ProgressBarDialog(auto_close=True)
        self.total_items_to_process = len(folder_paths) * len(self.enabled_postprocessors)
        self.processed_items = 0

        self._thread.now_processing.connect(self.on_now_processing)
        self._thread.processing_failed.connect(self.on_postprocess_fail)
        self._thread.processing_successful.connect(self.on_postprocess_success)
        self._thread.finished.connect(self.on_finished)
        self.dialog.cancelled.connect(self._thread.request_cancellation)

        self.dialog.show()
        self._thread.start()

    def on_postprocess_fail(self, folder_path):
        self.error_paths.add(folder_path)

    def on_postprocess_success(self, folder_path):
        self.success_paths.add(folder_path)

    def on_now_processing(self, folder_path, postprocessor_name):
        self.processed_items += 1
        if not self._thread._is_cancellation_requested:
            self.dialog.update_progress((self.processed_items / self.total_items_to_process) *
                                100, f"{_("POSTPROCESSORS_DIALOG_RUNNING_TEXT")}:\n{folder_path}\n{postprocessor_name}")

    def on_finished(self):
        if self._thread and self._thread._is_cancellation_requested:
            print("Postprocessing cancelled by user")
            self.dialog.update_progress(100, _("POSTPROCESSORS_DIALOG_CANCELLED_TEXT"))
        else:
            self.dialog.update_progress(100, _("POSTPROCESSORS_DIALOG_FINISHED_TEXT"))

        if self.error_paths:
            print(f"Postprocessing failed for folders:\n{"\n".join(self.error_paths)}")
        else:
            print("All postprocessors completed successfully!")

        self.postprocess_finished.emit(PostprocessResult(
            failed_folders=list(self.error_paths),
            processed_folders=list(self.success_paths)
        ))
