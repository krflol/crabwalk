import os
import sys
import shutil
import importlib.util
import subprocess
from textwrap import dedent
import hashlib
import ast
from .ir import ModuleIR, TypeIR

def ir_to_rust_type(typ: TypeIR) -> str:
    # Handle primitive types directly
    if typ.name in ["u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64", "f32", "f64", "bool", "String"]:
        return typ.name
    if typ.name == "int": return "i64"
    if typ.name == "float": return "f64"
    if typ.name == "str": return "String"
    
    if typ.name == "Vec":
        return f"Vec<{ir_to_rust_type(typ.generics[0])}>" if typ.generics else "Vec<_>"
    if typ.name == "Option":
        return f"Option<{ir_to_rust_type(typ.generics[0])}>" if typ.generics else "Option<_>"
    if typ.name == "Result":
        ok_t = ir_to_rust_type(typ.generics[0]) if len(typ.generics) > 0 else "_"
        err_t = ir_to_rust_type(typ.generics[1]) if len(typ.generics) > 1 else "String"
        return f"Result<{ok_t}, {err_t}>"
    if typ.name == "Mut":
        return f"&mut {ir_to_rust_type(typ.generics[0])}" if typ.generics else "&mut _"
    if typ.name == "Ref":
        return f"&{ir_to_rust_type(typ.generics[0])}" if typ.generics else "&_"
    if typ.name == "Owned":
        return ir_to_rust_type(typ.generics[0]) if typ.generics else "_"
        
    return typ.name

def compile_module(module_ir: ModuleIR, module_obj, package_root: str):
    # This is a transitional import. Once codegen is fully rewritten, we won't need it.
    from .codegen import RustCodeGenerator
    
    cargo_toml = dedent(f"""\
        [package]
        name = "__CRABWALK_CRATE_NAME__"
        version = "0.1.0"
        edition = "2021"

        [lib]
        name = "__CRABWALK_CRATE_NAME__"
        crate-type = ["cdylib"]

        [dependencies]
        pyo3 = {{ version = "0.29.2", features = ["extension-module"] }}
    """)
    for target, c in module_ir.crates.items():
        feat_str = ", ".join(f'"{f}"' for f in c["features"])
        cargo_toml += f'{c["name"]} = {{ version = "{c["version"]}", features = [{feat_str}] }}\n'
        
    lib_rs = "use pyo3::prelude::*;\n"
    has_serde = any("serde" == c["name"] for c in module_ir.crates.values())
    has_rayon = any("rayon" == c["name"] for c in module_ir.crates.values())
    
    if has_serde:
        lib_rs += "use serde::{Serialize, Deserialize};\n"
    if has_rayon:
        lib_rs += "use ::rayon::prelude::*;\n"
        
    for struct_ir in module_ir.structs:
        # Determine derives
        derives = ["Clone"]
        if has_serde:
            derives.extend(["Serialize", "Deserialize"])
        if struct_ir.derives:
            derives.extend(struct_ir.derives)
        
        derive_str = ", ".join(set(derives))
        lib_rs += f"#[pyclass]\n#[derive({derive_str})]\n"
        lib_rs += f"pub struct {struct_ir.name} {{\n"
        for field_name, field_type in struct_ir.fields:
            lib_rs += f"    #[pyo3(get, set)]\n    pub {field_name}: {ir_to_rust_type(field_type)},\n"
        lib_rs += "}\n\n"
        
        lib_rs += f"#[pymethods]\nimpl {struct_ir.name} {{\n"
        if struct_ir.is_class and struct_ir.methods:
            for method in struct_ir.methods:
                if method.name == "__init__":
                    args_str = ", ".join(f"{name}: {ir_to_rust_type(typ)}" for name, typ in method.args)
                    lib_rs += f"    #[new]\n    pub fn new({args_str}) -> Self {{\n"
                    generator = RustCodeGenerator(symbol_table=module_ir.crates)
                    init_fields = []
                    for stmt in method.body:
                        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Attribute) and stmt.targets[0].value.id == "self":
                            field = stmt.targets[0].attr
                            val = generator.get_expr(stmt.value)
                            init_fields.append(f"{field}: {val}")
                        else:
                            generator.visit(stmt)
                    lib_rs += "\n".join("        " + line for line in generator.code)
                    if init_fields:
                        lib_rs += f"\n        Self {{ {', '.join(init_fields)} }}\n"
                    else:
                        # Fallback to zero-arg initialization if possible
                        lib_rs += f"\n        Self {{ }}\n"
                    lib_rs += "    }\n\n"
                else:
                    args_str = ", ".join(f"{name}: {ir_to_rust_type(typ)}" for name, typ in method.args)
                    ret_str = ir_to_rust_type(method.returns)
                    sig_args = f"&mut self, {args_str}" if args_str else "&mut self"
                    
                    lib_rs += f"    pub fn {method.name}({sig_args}) -> {ret_str} {{\n"
                    generator = RustCodeGenerator(symbol_table=module_ir.crates)
                    for stmt in method.body:
                        generator.visit(stmt)
                    lib_rs += "\n".join("        " + line for line in generator.code)
                    lib_rs += "\n    }\n\n"
        else:
            # Add basic #[new]
            args_str = ", ".join(f"{n}: {ir_to_rust_type(t)}" for n, t in struct_ir.fields)
            init_str = ", ".join(n for n, _ in struct_ir.fields)
            lib_rs += f"    #[new]\n    pub fn new({args_str}) -> Self {{\n        Self {{ {init_str} }}\n    }}\n"
        lib_rs += "}\n\n"
        
    for enum_ir in module_ir.enums:
        derives = ["Clone", "PartialEq", "Eq"]
        if has_serde:
            derives.extend(["Serialize", "Deserialize"])
        if enum_ir.derives:
            derives.extend(enum_ir.derives)
            
        derive_str = ", ".join(set(derives))
        lib_rs += f"#[pyclass(eq, eq_int)]\n#[derive({derive_str})]\n"
        lib_rs += f"pub enum {enum_ir.name} {{\n"
        for variant in enum_ir.variants:
            lib_rs += f"    {variant},\n"
        lib_rs += "}\n\n"

    for func_ir in module_ir.functions:
        impl_args_str = ", ".join(f"mut {name}: {ir_to_rust_type(typ)}" for name, typ in func_ir.args)
        py_args_str = ", ".join(f"{name}: {ir_to_rust_type(typ)}" for name, typ in func_ir.args)
        ret_type = ir_to_rust_type(func_ir.returns)
        
        # Native Implementation function
        lib_rs += f"fn {func_ir.name}_impl({impl_args_str}) -> {ret_type} {{\n"
        generator = RustCodeGenerator(symbol_table=module_ir.crates)
        for stmt in func_ir.body:
            generator.visit(stmt)
        lib_rs += "\n".join("    " + line for line in generator.code)
        lib_rs += "\n}\n\n"
        
        py_ret_type = ret_type
        if ret_type.startswith("Result<"):
            # Extract the T from Result<T, E>
            ok_type = ret_type[7:ret_type.rfind(",")]
            py_ret_type = f"PyResult<{ok_type}>"
            
        # PyO3 Wrapper function
        lib_rs += f"#[pyfunction(name = \"{func_ir.name}\")]\n"
        if func_ir.detach:
            lib_rs += f"fn {func_ir.name}_py(py: Python<'_>"
            if py_args_str:
                lib_rs += f", {py_args_str}"
            lib_rs += f") -> {py_ret_type} {{\n"
            call_args = ", ".join(name for name, _ in func_ir.args)
            if ret_type.startswith("Result<"):
                lib_rs += f"    py.detach(move || {func_ir.name}_impl({call_args})).map_err(|e| pyo3::exceptions::PyException::new_err(format!(\"{{:?}}\", e)))\n"
            else:
                lib_rs += f"    py.detach(move || {func_ir.name}_impl({call_args}))\n"
            lib_rs += "}\n\n"
        else:
            lib_rs += f"fn {func_ir.name}_py({py_args_str}) -> {py_ret_type} {{\n"
            call_args = ", ".join(name for name, _ in func_ir.args)
            if ret_type.startswith("Result<"):
                lib_rs += f"    {func_ir.name}_impl({call_args}).map_err(|e| pyo3::exceptions::PyException::new_err(format!(\"{{:?}}\", e)))\n"
            else:
                lib_rs += f"    {func_ir.name}_impl({call_args})\n"
            lib_rs += "}\n\n"
    
    lib_rs += f"#[pymodule]\nfn __CRABWALK_CRATE_NAME__(m: &Bound<'_, PyModule>) -> PyResult<()> {{\n"
    for func_ir in module_ir.functions:
        lib_rs += f"    m.add_function(wrap_pyfunction!({func_ir.name}_py, m)?)?;\n"
    for struct_ir in module_ir.structs:
        lib_rs += f"    m.add_class::<{struct_ir.name}>()?;\n"
    for enum_ir in module_ir.enums:
        lib_rs += f"    m.add_class::<{enum_ir.name}>()?;\n"
    lib_rs += "    Ok(())\n}\n"
    
    h = hashlib.sha256()
    h.update(lib_rs.encode("utf-8"))
    h.update(cargo_toml.encode("utf-8"))
    h.update(sys.version.encode("utf-8"))
    try:
        rustc_ver = subprocess.run(["rustc", "-V"], capture_output=True, text=True, check=True).stdout
        h.update(rustc_ver.encode("utf-8"))
    except Exception:
        pass
        
    build_hash = h.hexdigest()[:16]
    
    crate_name = "crabwalk_" + build_hash
    lib_rs = lib_rs.replace("__CRABWALK_CRATE_NAME__", crate_name)
    cargo_toml = cargo_toml.replace("__CRABWALK_CRATE_NAME__", crate_name)
    
    base_dir = os.path.join(package_root, ".crabwalk", "builds", build_hash)
    gen_dir = base_dir
    src_dir = os.path.join(gen_dir, "src")
    
    target_dir = os.path.join(gen_dir, "target", "release")
    ext = ".pyd" if sys.platform == "win32" else ".so"
    dll_name = f"{crate_name}.dll" if sys.platform == "win32" else f"lib{crate_name}.so"
    if sys.platform == "darwin": dll_name = f"lib{crate_name}.dylib"
    
    artifact_path = os.path.join(target_dir, dll_name)
    pyd_path = os.path.join(gen_dir, f"{crate_name}{ext}")
    
    if not os.path.exists(pyd_path):
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(gen_dir, "Cargo.toml"), "w") as f:
            f.write(cargo_toml)
        with open(os.path.join(src_dir, "lib.rs"), "w") as f:
            f.write(lib_rs)
            
        print(f"Crabwalk: Compiling {crate_name} to Rust...")
        subprocess.run(["cargo", "build", "--release"], cwd=gen_dir, check=True)
        
        tmp_pyd_path = pyd_path + ".tmp"
        shutil.copy2(artifact_path, tmp_pyd_path)
        os.replace(tmp_pyd_path, pyd_path)
    
    spec = importlib.util.spec_from_file_location(crate_name, pyd_path)
    pyd_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pyd_module)
    
    # Hot-swap the attributes in the Python module
    setattr(module_obj, "_crabwalk_compiled", pyd_module)
    for ps in module_ir.structs:
        setattr(module_obj, ps.name, getattr(pyd_module, ps.name))
    for pe in module_ir.enums:
        setattr(module_obj, pe.name, getattr(pyd_module, pe.name))
    for pf in module_ir.functions:
        setattr(module_obj, pf.name, getattr(pyd_module, pf.name))
