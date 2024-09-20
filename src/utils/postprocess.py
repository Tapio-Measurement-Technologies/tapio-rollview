from gui.widgets.messagebox import show_info_msgbox, show_warn_msgbox
from utils.dynamic_loader import load_modules_from_folder
import os

base_path = os.path.dirname(os.path.abspath(__file__))
postprocessors = load_modules_from_folder(os.path.abspath(os.path.join(base_path, os.pardir, 'postprocessors')))

def get_postprocessors():
    return postprocessors

def toggle_postprocessor(postprocessor_module):
    postprocessor_module.enabled = not postprocessor_module.enabled
    if postprocessor_module.enabled:
        print(f"Enabled postprocessor '{postprocessor_module.description}'")
    else:
        print(f"Disabled postprocessor '{postprocessor_module.description}'")

def run_postprocessors(folder_paths):
    error_paths = set()
    for folder_path in folder_paths:
        for module_name, postprocessor in postprocessors.items():
            postprocessor_name = getattr(postprocessor, 'description', module_name)
            if postprocessor.enabled:
                print(f"Running postprocessor '{postprocessor_name}' for folder '{folder_path}'...")
                if not postprocessor.run(folder_path):
                    error_paths.add(folder_path)
    if error_paths:
        show_warn_msgbox(
            f"Postprocessors failed for the following paths:\n\n{'\n'.join(error_paths)}")
    else:
        show_info_msgbox("All postprocessors completed successfully!", "Success")
