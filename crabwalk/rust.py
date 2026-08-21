from .compiler import compile_rust_module

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

def crate(name, version=None, features=None):
    return RustCrate(name, version, features)

def struct(derive=None):
    def decorator(cls):
        cls._rust_derive = derive or []
        return cls
    return decorator

def enum(derive=None):
    def decorator(cls):
        cls._rust_derive = derive or []
        return cls
    return decorator

def raw(code: str):
    pass

def expr(code: str):
    pass

def fn(func=None, release_gil=False):
    """
    Decorator that compiles the given Python function into a native Rust extension
    and hot-swaps the runtime pointer.
    """
    def decorator(f):
        # The runtime compilation is triggered here when the module is loaded
        # Note: the real AST logic is handled in the builder, this just triggers it.
        from .compiler import compile_rust_module
        return compile_rust_module(f)

    if func is None:
        return decorator
    else:
        return decorator(func)
