"""Pure control-flow policies for statement lowering."""

from __future__ import annotations

from ..ir import IfIR, MatchIR, PatternMatchIR, ReturnIR, StatementIR


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
