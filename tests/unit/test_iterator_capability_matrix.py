from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import MethodCallIR, ReturnIR
from crabwalk.compiler.types import IteratorExecution, IteratorType


MATRIX_PREAMBLE = """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.struct
class Row:
    customer_id: rust.u64
    status: rust.String
"""


@pytest.mark.parametrize(
    ("name", "function", "execution", "source_fragment"),
    (
        (
            "copy_values",
            """
@rust.fn
def copy_values(
    values: rust.Ref[rust.Vec[rust.u64]], threshold: rust.u64,
) -> rust.Vec[rust.u64]:
    return values.iter().map(
        lambda value: value + 1
    ).filter(
        lambda value: value > threshold
    ).collect_vec()
""",
            IteratorExecution.SEQUENTIAL,
            ".iter().copied()",
        ),
        (
            "borrowed_strings",
            """
@rust.fn
def borrowed_strings(
    values: rust.Ref[rust.Vec[rust.String]], marker: rust.Str,
) -> rust.Vec[rust.String]:
    return values.iter_ref().filter(
        lambda value: value.contains(marker)
    ).map(
        lambda value: value.to_lowercase()
    ).collect_vec()
""",
            IteratorExecution.SEQUENTIAL,
            ".iter().filter(",
        ),
        (
            "borrowed_str",
            """
@rust.fn
def borrowed_str(text: rust.Str) -> rust.Vec[rust.String]:
    return text.lines().filter(
        lambda line: not line.is_empty()
    ).map(
        lambda line: line.to_lowercase()
    ).collect_vec()
""",
            IteratorExecution.SEQUENTIAL,
            ".lines().filter(",
        ),
        (
            "copy_tuples",
            """
@rust.fn
def copy_tuples(
    values: rust.Ref[rust.Vec[rust.Tuple[rust.u64, rust.u64]]],
) -> rust.Vec[rust.u64]:
    return values.iter().filter(
        lambda pair: pair[0] > 0
    ).map(
        lambda pair: pair[1]
    ).collect_vec()
""",
            IteratorExecution.SEQUENTIAL,
            ".iter().copied()",
        ),
        (
            "borrowed_domains",
            """
@rust.fn
def borrowed_domains(
    rows: rust.Ref[rust.Vec[Row]],
) -> rust.Vec[rust.u64]:
    return rows.iter_ref().filter(
        lambda row: row.status.starts_with("active")
    ).map(
        lambda row: row.customer_id
    ).collect_vec()
""",
            IteratorExecution.SEQUENTIAL,
            ".iter().filter(",
        ),
        (
            "parallel_copy",
            """
@rust.fn
def parallel_copy(
    values: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Vec[rust.u64]:
    return values.par_iter().copied().map(
        lambda value: value + 1
    ).filter(
        lambda value: value > 2
    ).collect_vec()
""",
            IteratorExecution.PARALLEL,
            ".par_iter().copied().map(",
        ),
        (
            "parallel_domains",
            """
@rust.fn
def parallel_domains(
    rows: rust.Ref[rust.Vec[Row]],
) -> rust.Vec[rust.u64]:
    return rows.par_iter().filter(
        lambda row: row.status.starts_with("active")
    ).map(
        lambda row: row.customer_id
    ).collect_vec()
""",
            IteratorExecution.PARALLEL,
            ".par_iter().filter(",
        ),
    ),
)
@capability_contract("iterator.copy-inline", "iterator.string-inline")
def test_iterator_cross_product_has_typed_three_stage_chains(
    tmp_path: Path,
    name: str,
    function: str,
    execution: IteratorExecution,
    source_fragment: str,
) -> None:
    source = tmp_path / f"{name}.py"
    source.write_text(MATRIX_PREAMBLE + function, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, f"_crabwalk_matrix_{name}")
    returned = ir.functions[0].body[0]

    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, MethodCallIR)
    assert returned.value.method == "collect_vec"
    assert isinstance(returned.value.receiver.type_ref, IteratorType)
    assert returned.value.receiver.type_ref.execution == execution
    assert source_fragment in generated.rust_source
    assert ".filter(" in generated.rust_source
    assert ".map(" in generated.rust_source
    assert ".collect::<Vec<_>>()" in generated.rust_source
