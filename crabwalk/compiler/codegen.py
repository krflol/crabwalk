import ast

class RustCodeGenerator(ast.NodeVisitor):
    def __init__(self):
        self.code = []
        self.declared_vars = set()

    def visit_Assign(self, node):
        if isinstance(node.targets[0], ast.Attribute):
            obj = self.get_expr(node.targets[0].value)
            attr = node.targets[0].attr
            value_code = self.get_expr(node.value)
            self.code.append(f"{obj}.{attr} = {value_code};")
        else:
            target = node.targets[0].id
            value_code = self.get_expr(node.value)
            if target not in self.declared_vars:
                self.code.append(f"let mut {target} = {value_code};")
                self.declared_vars.add(target)
            else:
                self.code.append(f"{target} = {value_code};")

    def visit_If(self, node):
        test_code = self.get_expr(node.test)
        self.code.append(f"if {test_code} {{")
        for stmt in node.body:
            self.visit(stmt)
        self.code.append("}")
        if node.orelse:
            self.code.append("else {")
            for stmt in node.orelse:
                self.visit(stmt)
            self.code.append("}")

    def visit_While(self, node):
        test_code = self.get_expr(node.test)
        self.code.append(f"while {test_code} {{")
        for stmt in node.body:
            self.visit(stmt)
        self.code.append("}")

    def visit_For(self, node):
        target = self.get_expr(node.target)
        iter_code = self.get_expr(node.iter)
        self.code.append(f"for {target} in {iter_code} {{")
        for stmt in node.body:
            self.visit(stmt)
        self.code.append("}")

    def visit_Return(self, node):
        if node.value is None:
            self.code.append("return;")
        else:
            value_code = self.get_expr(node.value)
            self.code.append(f"return {value_code};")

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
            if getattr(node.value.func.value, "id", None) == "rust" and node.value.func.attr == "raw":
                raw_str = node.value.args[0].value
                self.code.append(raw_str)
                return
                
        expr_code = self.get_expr(node.value)
        self.code.append(f"{expr_code};")

    def get_expr(self, node):
        if isinstance(node, ast.Name):
            if node.id == "True": return "true"
            if node.id == "False": return "false"
            if node.id == "None": return "None"
            return node.id
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return f'"{node.value}".to_string()'
            elif isinstance(node.value, bool):
                return "true" if node.value else "false"
            elif node.value is None:
                return "None"
            return str(node.value)
        elif isinstance(node, ast.BinOp):
            left = self.get_expr(node.left)
            right = self.get_expr(node.right)
            op = self.get_op(node.op)
            return f"({left} {op} {right})"
        elif isinstance(node, ast.Compare):
            left = self.get_expr(node.left)
            right = self.get_expr(node.comparators[0])
            op = self.get_comp_op(node.ops[0])
            return f"({left} {op} {right})"
        elif isinstance(node, ast.BoolOp):
            op = " && " if isinstance(node.op, ast.And) else " || "
            values = [self.get_expr(v) for v in node.values]
            return f"({op.join(values)})"
        elif isinstance(node, ast.UnaryOp):
            op = "!" if isinstance(node.op, ast.Not) else "-"
            operand = self.get_expr(node.operand)
            return f"{op}{operand}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                obj = node.func.value.id if isinstance(node.func.value, ast.Name) else self.get_expr(node.func.value)
                method = node.func.attr
                if obj == "serde_json" and method == "from_str":
                    typ = node.args[0].id
                    data = self.get_expr(node.args[1])
                    return f"serde_json::from_str::<{typ}>(&{data}).unwrap()"
            
            # Catch rust.Some, rust.Ok, rust.expr, etc.
            if isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "rust":
                if node.func.attr == "Some":
                    return f"Some({self.get_expr(node.args[0])})"
                if node.func.attr == "Ok":
                    return f"Ok({self.get_expr(node.args[0])})"
                if node.func.attr == "Err":
                    return f"Err({self.get_expr(node.args[0])})"
                if node.func.attr == "expr":
                    return node.args[0].value

            func = self.get_expr(node.func)
            if func and func[0].isupper():
                func = f"{func}::new"
            args = [self.get_expr(arg) for arg in node.args]
            return f"{func}({', '.join(args)})"
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "rust" and node.attr == "None":
                return "None"
            obj = self.get_expr(node.value)
            attr = node.attr
            if obj and obj[0].isupper():
                return f"{obj}::{attr}"
            if attr in ["unwrap", "is_some", "is_none", "is_ok", "is_err", "is_empty", "push", "pop"]:
                return f"{obj}.{attr}"
            return f"{obj}.{attr}.clone()"
        else:
            raise NotImplementedError(f"Unsupported AST node: {type(node)}")

    def get_op(self, op):
        if isinstance(op, ast.Add): return "+"
        elif isinstance(op, ast.Sub): return "-"
        elif isinstance(op, ast.Mult): return "*"
        elif isinstance(op, ast.Div): return "/"
        elif isinstance(op, ast.Mod): return "%"
        else: raise NotImplementedError(f"Unsupported binary op: {type(op)}")

    def get_comp_op(self, op):
        if isinstance(op, ast.LtE): return "<="
        elif isinstance(op, ast.Lt): return "<"
        elif isinstance(op, ast.GtE): return ">="
        elif isinstance(op, ast.Gt): return ">"
        elif isinstance(op, ast.Eq): return "=="
        elif isinstance(op, ast.NotEq): return "!="
        else: raise NotImplementedError(f"Unsupported comparison op: {type(op)}")
