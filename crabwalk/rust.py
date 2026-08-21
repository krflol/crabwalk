import functools
import sys

class RustSymbol:
    pass

class RustType(RustSymbol):
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return f"RustType({self.name})"

class RustGenericType(RustType):
    def __init__(self, name):
        super().__init__(name)
    def __getitem__(self, item):
        return self

class RustTrait(RustSymbol):
    def __init__(self, name):
        self.name = name

class RustCrateMember(RustSymbol):
    def __init__(self, crate_name, member_name):
        self.crate_name = crate_name
        self.member_name = member_name

class RustCrate(RustSymbol):
    def __init__(self, name, version="*", features=None):
        self.name = name
        self.version = version
        self.features = features or []
        
    def __getattr__(self, item):
        return RustCrateMember(self.name, item)

def crate(name: str, version: str = "*", features: list[str] | None = None) -> RustCrate:
    return RustCrate(name=name, version=version, features=features)

# Primitives
i8 = RustType("i8")
i16 = RustType("i16")
i32 = RustType("i32")
i64 = RustType("i64")
i128 = RustType("i128")
u8 = RustType("u8")
u16 = RustType("u16")
u32 = RustType("u32")
u64 = RustType("u64")
u128 = RustType("u128")
f32 = RustType("f32")
f64 = RustType("f64")
bool = RustType("bool")
String = RustType("String")

# Generics
Mut = RustGenericType("Mut")
Ref = RustGenericType("Ref")
Owned = RustGenericType("Owned")
Vec = RustGenericType("Vec")
Option = RustGenericType("Option")
Result = RustGenericType("Result")
HashMap = RustGenericType("HashMap")
HashSet = RustGenericType("HashSet")

def pyclass(derive=None):
    def decorator(cls):
        cls._is_crabwalk_class = True
        cls._rust_derives = derive or []
        return cls
    
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
        
        @functools.wraps(f)
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
    raise RuntimeError("rust.raw() is only valid inside Crabwalk-compiled code")

def expr(code_str: str) -> any:
    raise RuntimeError("rust.expr() is only valid inside Crabwalk-compiled code")

def compile(module):
    from .compiler import compile_package
    compile_package(module)

def unwrap(val):
    raise RuntimeError("rust.unwrap() is only valid inside Crabwalk-compiled code")

def try_(val):
    raise RuntimeError("rust.try_() is only valid inside Crabwalk-compiled code")

def Ok(val):
    raise RuntimeError("rust.Ok() is only valid inside Crabwalk-compiled code")

def Err(val):
    raise RuntimeError("rust.Err() is only valid inside Crabwalk-compiled code")

def __getattr__(name):
    # Fallback for dynamic types if needed, though they shouldn't be relied upon.
    return RustType(name)
