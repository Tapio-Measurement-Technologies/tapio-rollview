import importlib.util
import os

def load_modules_from_folder(folder_path):
    modules = {}
    for filename in os.listdir(folder_path):
        if filename.endswith('.py') and filename != '__init__.py':
            module_name = filename[:-3]
            module_path = os.path.join(folder_path, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, 'description') and callable(getattr(module, 'description', None)):
                module.description = module.description()
            if hasattr(module, 'enabled'):
                module.enabled = module.enabled
            modules[module_name] = module
    return modules