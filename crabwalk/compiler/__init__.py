import inspect
import ast
import os
from .frontend import parse_module
from .backend import compile_module

def compile_package(module_obj):
    source = inspect.getsource(module_obj)
    tree = ast.parse(source)
    
    module_ir = parse_module(module_obj.__name__, tree)
    
    module_path = inspect.getfile(module_obj)
    package_root = os.path.dirname(os.path.abspath(module_path))
    
    compile_module(module_ir, module_obj, package_root)
