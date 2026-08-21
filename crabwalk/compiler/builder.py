import ast
import inspect
import os
import subprocess
import sys
import importlib.util
import shutil
from textwrap import dedent
from .codegen import RustCodeGenerator

def resolve_type(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute):
            outer = node.value.attr
        elif isinstance(node.value, ast.Name):
            outer = node.value.id
        else:
            outer = "Unknown"
        inner = resolve_type(node.slice)
        
        # Nested generics handling
        if outer == "Mut":
            return f"&mut {inner}"
        elif outer == "Vec":
            return f"Vec<{inner}>"
        elif outer == "Option":
            return f"Option<{inner}>"
        elif outer == "Result":
            # Result expects 2 arguments, let's just handle simple 1 arg or comma for now
            return f"Result<{inner}, String>"
        return f"{outer}<{inner}>"
    raise Exception(f"Unknown type {ast.dump(node)}")

def compile_rust_module(func):
    module_name = func.__module__
    if module_name == "__main__":
        module = sys.modules["__main__"]
    else:
        module = sys.modules[module_name]
        
    if hasattr(module, "_crabwalk_compiled"):
        return getattr(module._crabwalk_compiled, func.__name__)
        
    source = inspect.getsource(module)
    tree = ast.parse(source)
    
    crates = {}
    structs_code = []
    functions_code = []
    pyfunctions = []
    pystructs = []
    rust_enums = {}
    
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "crate":
                target_name = node.targets[0].id
                crate_name = node.value.args[0].value
                kwargs = {kw.arg: kw.value.value if not isinstance(kw.value, ast.List) else [x.value for x in kw.value.elts] for kw in node.value.keywords}
                crates[target_name] = {"name": crate_name, "version": kwargs.get("version", "*"), "features": kwargs.get("features", [])}
                
        elif isinstance(node, ast.ClassDef):
            is_rust_struct = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "struct" for d in node.decorator_list)
            is_rust_enum = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "enum" for d in node.decorator_list)
            
            if is_rust_enum:
                variants = []
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        variants.append(stmt.targets[0].id)
                rust_enums[node.name] = variants
                
                derives = ["Clone", "PartialEq", "Eq", "PartialOrd", "Ord"]
                if "serde" in [c["name"] for c in crates.values()]:
                    derives.extend(["Serialize", "Deserialize"])
                    
                structs_code.append(
                    f"#[pyclass]\n"
                    f"#[derive({', '.join(derives)})]\n"
                    f"pub enum {node.name} {{\n" + ",\n".join(f"    {v}" for v in variants) + "\n}\n"
                )
                pystructs.append(node.name)
            
            elif is_rust_struct:
                fields = []
                init_assignments = []
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign):
                        name = stmt.target.id
                        typ = resolve_type(stmt.annotation)
                        fields.append(f"    #[pyo3(get, set)]\n    pub {name}: {typ},")
                        
                        if typ in ["u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"]:
                            init_assignments.append(f"{name}: 0")
                        elif typ in ["f32", "f64"]:
                            init_assignments.append(f"{name}: 0.0")
                        elif typ == "bool":
                            init_assignments.append(f"{name}: false")
                        elif typ == "String":
                            init_assignments.append(f'{name}: String::new()')
                        elif typ.startswith("Vec<"):
                            init_assignments.append(f'{name}: Vec::new()')
                        elif typ.startswith("Option<"):
                            init_assignments.append(f'{name}: None')
                        elif typ in rust_enums:
                            init_assignments.append(f'{name}: {typ}::{rust_enums[typ][0]}')
                        else:
                            # Fallback if we don't know the type (e.g. nested struct without explicit tracking here)
                            pass
                
                derives = ["Clone"]
                if "serde" in [c["name"] for c in crates.values()]:
                    derives.extend(["Serialize", "Deserialize"])
                    
                structs_code.append(
                    f"#[pyclass]\n"
                    f"#[derive({', '.join(derives)})]\n"
                    f"pub struct {node.name} {{\n" + "\n".join(fields) + "\n}\n" +
                    f"#[pymethods]\n"
                    f"impl {node.name} {{\n"
                    f"    #[new]\n"
                    f"    pub fn new() -> Self {{\n"
                    f"        Self {{ {', '.join(init_assignments)} }}\n"
                    f"    }}\n"
                    f"}}\n"
                )
                pystructs.append(node.name)
                
        elif isinstance(node, ast.FunctionDef):
            is_rust_fn = False
            release_gil = False
            for d in node.decorator_list:
                if isinstance(d, ast.Attribute) and d.attr == "fn":
                    is_rust_fn = True
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "fn":
                    is_rust_fn = True
                    for kw in d.keywords:
                        if kw.arg == "release_gil" and getattr(kw.value, "value", False) is True:
                            release_gil = True

            if is_rust_fn:
                args = []
                if release_gil:
                    args.append("py: Python")
                    
                for arg in node.args.args:
                    annotation = resolve_type(arg.annotation)
                    args.append(f"mut {arg.arg}: {annotation}")
                
                returns = resolve_type(node.returns) if node.returns else "()"
                
                gen = RustCodeGenerator()
                for arg in node.args.args:
                    gen.declared_vars.add(arg.arg)
                for stmt in node.body:
                    gen.visit(stmt)
                
                if release_gil:
                    body_code = "\n".join(gen.code)
                    indented = "\n".join(f"        {line}" for line in body_code.split("\n"))
                    fn_body = f"    py.allow_threads(move || {{\n{indented}\n    }})"
                else:
                    fn_body = "\n".join(gen.code)
                    
                functions_code.append(f"#[pyfunction]\nfn {node.name}({', '.join(args)}) -> {returns} {{\n{fn_body}\n}}")
                pyfunctions.append(node.name)
                
    crate_name = "crabwalk_compiled_" + os.path.basename(inspect.getfile(module)).replace(".py", "")
    
    cargo_toml = dedent(f"""\
        [package]
        name = "{crate_name}"
        version = "0.1.0"
        edition = "2021"

        [lib]
        name = "{crate_name}"
        crate-type = ["cdylib"]

        [dependencies]
        pyo3 = {{ version = "0.19.0", features = ["extension-module"] }}
    """)
    for target, c in crates.items():
        feat_str = ", ".join(f'"{f}"' for f in c["features"])
        cargo_toml += f'{c["name"]} = {{ version = "{c["version"]}", features = [{feat_str}] }}\n'
        
    lib_rs = "use pyo3::prelude::*;\n"
    if "serde" in [c["name"] for c in crates.values()]:
        lib_rs += "use serde::{Serialize, Deserialize};\n"
    if "rayon" in [c["name"] for c in crates.values()]:
        lib_rs += "use rayon::prelude::*;\n"
        
    lib_rs += "\n".join(structs_code) + "\n"
    lib_rs += "\n".join(functions_code) + "\n"
    
    lib_rs += f"#[pymodule]\nfn {crate_name}(_py: Python, m: &PyModule) -> PyResult<()> {{\n"
    for pf in pyfunctions:
        lib_rs += f"    m.add_function(wrap_pyfunction!({pf}, m)?)?;\n"
    for ps in pystructs:
        lib_rs += f"    m.add_class::<{ps}>()?;\n"
    lib_rs += "    Ok(())\n}\n"
    
    base_dir = os.path.join(os.getcwd(), ".crabwalk")
    gen_dir = os.path.join(base_dir, "generated", crate_name)
    src_dir = os.path.join(gen_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    
    with open(os.path.join(gen_dir, "Cargo.toml"), "w") as f:
        f.write(cargo_toml)
    with open(os.path.join(src_dir, "lib.rs"), "w") as f:
        f.write(lib_rs)
        
    print(f"Crabwalk: Compiling {crate_name} to Rust...")
    subprocess.run(["cargo", "build", "--release"], cwd=gen_dir, check=True)
    
    target_dir = os.path.join(gen_dir, "target", "release")
    ext = ".pyd" if sys.platform == "win32" else ".so"
    dll_name = f"{crate_name}.dll" if sys.platform == "win32" else f"lib{crate_name}.so"
    if sys.platform == "darwin": dll_name = f"lib{crate_name}.dylib"
    
    artifact_path = os.path.join(target_dir, dll_name)
    pyd_path = os.path.join(gen_dir, f"{crate_name}{ext}")
    shutil.copy2(artifact_path, pyd_path)
    
    spec = importlib.util.spec_from_file_location(crate_name, pyd_path)
    pyd_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pyd_module)
    
    setattr(module, "_crabwalk_compiled", pyd_module)
    
    for ps in pystructs:
        setattr(module, ps, getattr(pyd_module, ps))
        
    return getattr(pyd_module, func.__name__)
