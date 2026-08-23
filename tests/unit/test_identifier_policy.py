from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.naming import (
    RUST_2024_FORBIDDEN_BINDINGS,
    RUST_2024_RESERVED_KEYWORDS,
    RUST_2024_STRICT_KEYWORDS,
    RUST_2024_WEAK_KEYWORDS,
    dependency_crate_alias,
    is_rust_2024_identifier,
)
from crabwalk.diagnostics import CrabwalkCompilationError


STRICT_2024 = frozenset(
    {
        "_",
        "as",
        "async",
        "await",
        "break",
        "const",
        "continue",
        "crate",
        "dyn",
        "else",
        "enum",
        "extern",
        "false",
        "fn",
        "for",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "match",
        "mod",
        "move",
        "mut",
        "pub",
        "ref",
        "return",
        "self",
        "Self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "type",
        "unsafe",
        "use",
        "where",
        "while",
    }
)
RESERVED_2024 = frozenset(
    {
        "abstract",
        "become",
        "box",
        "do",
        "final",
        "gen",
        "macro",
        "override",
        "priv",
        "try",
        "typeof",
        "unsized",
        "virtual",
        "yield",
    }
)
WEAK_2024 = frozenset({"macro_rules", "raw", "safe", "union"})
POSITION_DIAGNOSTICS = {
    "function": "CRAB105",
    "parameter": "CRAB210",
    "local": "CRAB210",
    "loop target": "CRAB210",
    "closure parameter": "CRAB210",
    "pattern binding": "CRAB210",
    "struct name": "CRAB150",
    "struct field": "CRAB210",
    "enum name": "CRAB160",
    "enum variant": "CRAB210",
    "enum payload field": "CRAB210",
    "trait name": "CRAB191",
    "trait method": "CRAB191",
    "type parameter": "CRAB180",
    "lifetime parameter": "CRAB180",
    "method name": "CRAB190",
    "crate binding": "CRAB130",
}


def test_rust_2024_keyword_tables_match_the_reference() -> None:
    assert RUST_2024_STRICT_KEYWORDS == STRICT_2024
    assert RUST_2024_RESERVED_KEYWORDS == RESERVED_2024
    assert RUST_2024_WEAK_KEYWORDS == WEAK_2024
    assert RUST_2024_FORBIDDEN_BINDINGS == STRICT_2024 | RESERVED_2024


@pytest.mark.parametrize("name", sorted(STRICT_2024 | RESERVED_2024))
def test_every_strict_and_reserved_keyword_is_rejected(name: str) -> None:
    assert is_rust_2024_identifier(name) is False


@pytest.mark.parametrize("name", sorted(WEAK_2024))
def test_weak_keywords_remain_valid_in_crabwalk_binding_positions(name: str) -> None:
    assert is_rust_2024_identifier(name) is True


@pytest.mark.parametrize("name", ["", "9lives", "two-parts", "café", "r#gen"])
def test_nonportable_or_raw_identifiers_are_rejected(name: str) -> None:
    assert is_rust_2024_identifier(name) is False


@pytest.mark.parametrize(
    ("position", "source_text"),
    [
        (
            "function",
            """\
from crabwalk import rust
@rust.fn
def gen() -> rust.u64:
    return 1
""",
        ),
        (
            "parameter",
            """\
from crabwalk import rust
@rust.fn
def invalid(gen: rust.u64) -> rust.u64:
    return gen
""",
        ),
        (
            "local",
            """\
from crabwalk import rust
@rust.fn
def invalid() -> rust.u64:
    gen: rust.u64 = 1
    return gen
""",
        ),
        (
            "loop target",
            """\
from crabwalk import rust
@rust.fn
def invalid() -> rust.u64:
    total: rust.u64 = 0
    for gen in range(1):
        total += gen
    return total
""",
        ),
        (
            "closure parameter",
            """\
from crabwalk import rust
@rust.fn
def invalid() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1])
    return values.iter().map(lambda gen: gen).sum()
""",
        ),
        (
            "pattern binding",
            """\
from crabwalk import rust
@rust.fn
def invalid(value: rust.u64) -> rust.u64:
    match value:
        case gen:
            return gen
""",
        ),
        (
            "struct name",
            """\
from crabwalk import rust
@rust.struct
class gen:
    value: rust.u64
""",
        ),
        (
            "struct field",
            """\
from crabwalk import rust
@rust.struct
class Value:
    gen: rust.u64
""",
        ),
        (
            "enum name",
            """\
from crabwalk import rust
@rust.enum
class gen:
    Ready = rust.variant()
""",
        ),
        (
            "enum variant",
            """\
from crabwalk import rust
@rust.enum
class Status:
    gen = rust.variant()
""",
        ),
        (
            "enum payload field",
            """\
from crabwalk import rust
@rust.enum
class Status:
    Ready = rust.variant(gen=rust.u64)
""",
        ),
        (
            "trait name",
            """\
from crabwalk import rust
gen = rust.trait("gen", run=rust.u64)
""",
        ),
        (
            "trait method",
            """\
from crabwalk import rust
Draw = rust.trait("Draw", gen=rust.u64)
""",
        ),
        (
            "type parameter",
            """\
from crabwalk import rust
gen = rust.typevar("gen")
@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        ),
        (
            "lifetime parameter",
            """\
from crabwalk import rust
gen = rust.lifetime("gen")
@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        ),
        (
            "method name",
            """\
from crabwalk import rust
@rust.struct
class Value:
    number: rust.u64
@rust.method(Value, name="gen")
def read(value: rust.Ref[Value]) -> rust.u64:
    return value.number
""",
        ),
        (
            "crate binding",
            """\
from crabwalk import rust
gen = rust.crate("serde", version="1")
@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        ),
    ],
)
def test_reserved_2024_name_fails_in_each_source_binding_family(
    tmp_path: Path,
    position: str,
    source_text: str,
) -> None:
    source = tmp_path / f"invalid_{position.replace(' ', '_')}.py"
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == POSITION_DIAGNOSTICS[position]
    assert diagnostic.span is not None


def test_weak_keywords_generate_as_ordinary_rust_bindings(tmp_path: Path) -> None:
    source = tmp_path / "weak_keywords.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Value:
    union: rust.u64

@rust.enum
class Status:
    raw = rust.variant()
    safe = rust.variant(value=rust.u64)

@rust.fn
def union(union: rust.u64) -> rust.u64:
    raw: rust.u64 = union
    safe: rust.u64 = raw
    macro_rules: rust.u64 = safe
    return macro_rules
""",
        encoding="utf-8",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_weak_keywords")

    assert "pub union: u64" in generated.rust_source
    assert "raw," in generated.rust_source
    assert "union: u64" in generated.rust_source
    assert "let raw: u64 = union;" in generated.rust_source
    assert "let safe: u64 = raw;" in generated.rust_source
    assert "let macro_rules: u64 = safe;" in generated.rust_source


def test_reserved_crate_package_name_uses_internal_cargo_key() -> None:
    assert dependency_crate_alias("gen") is None
    assert dependency_crate_alias("union") == "union"
