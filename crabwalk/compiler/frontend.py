import ast
from .ir import ModuleIR, FunctionIR, StructIR, EnumIR, TypeIR, ExprIR, StmtIR

def parse_type(node) -> TypeIR:
    if isinstance(node, ast.Name):
        return TypeIR(name=node.id)
    elif isinstance(node, ast.Attribute):
        # e.g. rust.u64
        return TypeIR(name=node.attr)
    elif isinstance(node, ast.Subscript):
        # e.g. rust.Vec[rust.f64]
        base = parse_type(node.value)
        
        # Handle Result[T, E] where slice is a Tuple
        if isinstance(node.slice, ast.Tuple):
            generics = [parse_type(elt) for elt in node.slice.elts]
        else:
            generics = [parse_type(node.slice)]
            
        base.generics = generics
        return base
    
    raise ValueError(f"Unsupported type annotation: {ast.dump(node)}")

def extract_derives(decorator) -> list[str]:
    derives = []
    if isinstance(decorator, ast.Call):
        for kw in decorator.keywords:
            if kw.arg == "derive" and isinstance(kw.value, ast.List):
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Attribute):
                        derives.append(elt.attr)
    return derives

def parse_module(module_name: str, tree: ast.Module) -> ModuleIR:
    functions = []
    structs = []
    enums = []
    crates = {}
    
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "crate":
                target_name = node.targets[0].id
                dep_crate_name = node.value.args[0].value
                kwargs = {kw.arg: kw.value.value if not isinstance(kw.value, ast.List) else [x.value for x in kw.value.elts] for kw in node.value.keywords}
                crates[target_name] = {"name": dep_crate_name, "version": kwargs.get("version", "*"), "features": kwargs.get("features", [])}
                
        elif isinstance(node, ast.ClassDef):
            is_rust_struct = False
            is_rust_enum = False
            is_rust_class = False
            derives = []
            
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "struct":
                    is_rust_struct = True
                    derives = extract_derives(d)
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "enum":
                    is_rust_enum = True
                    derives = extract_derives(d)
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("class_", "pyclass"):
                    is_rust_class = True
                    derives = extract_derives(d)
                # handle non-call decorators
                elif isinstance(d, ast.Attribute):
                    if d.attr == "struct": is_rust_struct = True
                    if d.attr == "enum": is_rust_enum = True
                    if d.attr in ("class_", "pyclass"): is_rust_class = True
            
            if is_rust_enum:
                variants = [stmt.targets[0].id for stmt in node.body if isinstance(stmt, ast.Assign)]
                enums.append(EnumIR(name=node.name, variants=variants, derives=derives))
                
            elif is_rust_struct or is_rust_class:
                fields = []
                methods = []
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign):
                        fields.append((stmt.target.id, parse_type(stmt.annotation)))
                    elif isinstance(stmt, ast.FunctionDef) and is_rust_class:
                        # Parse method
                        args = [(arg.arg, parse_type(arg.annotation) if arg.annotation else TypeIR(name="Any")) for arg in stmt.args.args if arg.arg != "self"]
                        # We must adjust node.args.args since stmt is the FunctionDef
                        m_args = []
                        for arg in stmt.args.args:
                            if arg.arg == "self":
                                continue
                            m_args.append((arg.arg, parse_type(arg.annotation) if arg.annotation else TypeIR(name="Any")))
                            
                        returns = parse_type(stmt.returns) if stmt.returns else TypeIR(name="()")
                        body = stmt.body
                        methods.append(FunctionIR(name=stmt.name, args=m_args, returns=returns, body=body, detach=False))
                
                structs.append(StructIR(name=node.name, fields=fields, derives=derives, methods=methods, is_class=is_rust_class))
                
        elif isinstance(node, ast.FunctionDef):
            is_rust_fn = False
            detach = False
            for d in node.decorator_list:
                if isinstance(d, ast.Attribute) and d.attr == "fn":
                    is_rust_fn = True
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "fn":
                    is_rust_fn = True
                    for kw in d.keywords:
                        if kw.arg == "detach" and getattr(kw.value, "value", False) is True:
                            detach = True

            if is_rust_fn:
                args = [(arg.arg, parse_type(arg.annotation)) for arg in node.args.args]
                returns = parse_type(node.returns) if node.returns else TypeIR(name="()")
                
                # Currently storing raw AST body. Later we'll parse this into IR.
                body = node.body
                
                functions.append(FunctionIR(name=node.name, args=args, returns=returns, body=body, detach=detach))

    return ModuleIR(name=module_name, functions=functions, structs=structs, enums=enums, crates=crates)
