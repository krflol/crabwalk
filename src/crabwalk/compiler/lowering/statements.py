"""Pure control-flow policies for statement lowering."""

from __future__ import annotations

import ast

from ..ir import IfIR, MatchIR, PatternMatchIR, ReturnIR, StatementIR


def executable_function_body(statements: list[ast.stmt]) -> list[ast.stmt]:
    """Return function statements after Python's metadata-only docstring."""

    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        return statements[1:]
    return statements


def block_returns(statements: tuple[StatementIR, ...]) -> bool:
    """Return whether every reachable path in a lowered block returns."""

    for statement in statements:
        if isinstance(statement, ReturnIR):
            return True
        if (
            isinstance(statement, IfIR)
            and statement.otherwise
            and block_returns(statement.body)
            and block_returns(statement.otherwise)
        ):
            return True
        if (
            isinstance(statement, (MatchIR, PatternMatchIR))
            and statement.arms
            and all(block_returns(arm.body) for arm in statement.arms)
        ):
            return True
    return False
