"""Pure expression-lowering policies shared by the typed frontend."""

from __future__ import annotations

import ast
import re
from typing import Literal

from ..ir import TypeRef

BinaryOperator = Literal["add", "subtract", "multiply", "divide", "remainder"]


def binary_operator(node: ast.operator) -> BinaryOperator | None:
    """Map one supported Python operator node to its semantic IR spelling."""

    mapping: dict[type[ast.operator], BinaryOperator] = {
        ast.Add: "add",
        ast.Sub: "subtract",
        ast.Mult: "multiply",
        ast.Div: "divide",
        ast.Mod: "remainder",
    }
    return mapping.get(type(node))


def integer_fits(value: int, type_ref: TypeRef) -> bool:
    """Return whether a literal is representable by one semantic integer type."""

    if type_ref.rust_name == "usize":
        return 0 <= value <= (1 << 64) - 1
    match = re.fullmatch(r"([iu])(8|16|32|64|128)", type_ref.rust_name)
    if match is None:
        return False
    signed = match.group(1) == "i"
    bits = int(match.group(2))
    if signed:
        return -(1 << (bits - 1)) <= value <= (1 << (bits - 1)) - 1
    return 0 <= value <= (1 << bits) - 1
