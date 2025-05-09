import importlib.util
import os
import traceback


def load_modules_from_folder(folder_path):
    modules = {}
    for filename in os.listdir(folder_path):
        try:
            if filename.endswith('.py') and filename != '__init__.py':
                module_name = filename[:-3]
                module_path = os.path.join(folder_path, filename)
                spec = importlib.util.spec_from_file_location(
                    module_name, module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, 'description') and callable(getattr(module, 'description', None)):
                    module.description = module.description()
                modules[module_name] = module
                print(f"Loaded postprocessor '{module_name}'")
        except Exception as e:
            print(f"Failed to load postprocessors: {e}")
            traceback.print_exc()
    return modules
