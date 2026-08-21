import inspect
import sys

class RustMarker:
    def __init__(self, name):
        self.name = name

# Primitives
i8 = RustMarker("i8")
i16 = RustMarker("i16")
i32 = RustMarker("i32")
i64 = RustMarker("i64")
i128 = RustMarker("i128")
u8 = RustMarker("u8")
u16 = RustMarker("u16")
u32 = RustMarker("u32")
u64 = RustMarker("u64")
u128 = RustMarker("u128")
f32 = RustMarker("f32")
f64 = RustMarker("f64")
bool = RustMarker("bool")

String = RustMarker("String")

# Markers for derived traits
Serialize = RustMarker("Serialize")
Deserialize = RustMarker("Deserialize")

class TypeModifier:
    def __getitem__(self, item):
        return self

Mut = TypeModifier()
Vec = TypeModifier()
Option = TypeModifier()
Result = TypeModifier()
HashMap = TypeModifier()
HashSet = TypeModifier()

class RustCrate:
    def __init__(self, name, version=None, features=None):
        self.name = name
        self.version = version
        self.features = features or []
        
    def __getattr__(self, item):
        return RustMarker(f"{self.name}.{item}")

def crate(name, version="*", features=None):
    pass

def pyclass(derive=None):
    def decorator(cls):
        cls._is_crabwalk_class = True
        cls._rust_derives = derive or []
        return cls
    
    # if it was called without parentheses: @rust.pyclass
    if callable(derive):
        cls = derive
        derive = None
        return decorator(cls)
        
    return decorator

def struct(derive=None):
    def decorator(cls):
        cls._is_crabwalk_struct = True
        cls._rust_derives = derive or []
        return cls
    return decorator

def enum(derive=None):
    def decorator(cls):
        cls._is_crabwalk_enum = True
        cls._rust_derives = derive or []
        return cls
    return decorator

def fn(func=None, detach=False):
    def decorator(f):
        f._rust_detach = detach
        
        def wrapper(*args, **kwargs):
            if not hasattr(wrapper, "_compiled"):
                from .compiler import compile_package
                module = sys.modules[f.__module__]
                compile_package(module)
                wrapper._compiled = getattr(module, f.__name__)
            return wrapper._compiled(*args, **kwargs)
            
        wrapper._is_crabwalk_fn = True
        return wrapper
        
    if func is None:
        return decorator
    else:
        return decorator(func)

def raw(code_str: str):
    pass

def expr(code_str: str) -> any:
    pass

def __getattr__(name):
    return type(name, (), {})

class TypeMeta(type):
    def __getitem__(cls, type_args):
        return cls

class Vec(metaclass=TypeMeta): pass
class Option(metaclass=TypeMeta): pass
class Result(metaclass=TypeMeta): pass

u8 = type("u8", (), {})
u16 = type("u16", (), {})
u32 = type("u32", (), {})
u64 = type("u64", (), {})
i8 = type("i8", (), {})
i16 = type("i16", (), {})
i32 = type("i32", (), {})
i64 = type("i64", (), {})
f32 = type("f32", (), {})
def compile(module):
    from .compiler import compile_package
    compile_package(module)
