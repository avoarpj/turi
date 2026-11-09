from pathlib import Path
import importlib.util

def import_func_from_pyfile(file_path: Path, funcName: str):
    module_name = f"dynamic_{file_path.stem}"

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load python script: {file_path}")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return getattr(module, funcName)
