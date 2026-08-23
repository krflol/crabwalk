from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.naming import (
    COMPILER_LIFETIME_PREFIX,
    COMPILER_TYPE_PREFIX,
    COMPILER_VALUE_PREFIX,
    CRABWALK_BUILTIN_TYPE_NAMES,
    RUST_2024_FORBIDDEN_BINDINGS,
    RUST_PRELUDE_VALUE_CONSTRUCTORS,
    RUST_2024_RESERVED_KEYWORDS,
    RUST_2024_STRICT_KEYWORDS,
    RUST_2024_WEAK_KEYWORDS,
    dependency_crate_alias,
    is_crabwalk_lifetime_parameter,
    is_crabwalk_type_parameter,
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


@pytest.mark.parametrize("name", sorted(RUST_PRELUDE_VALUE_CONSTRUCTORS))
def test_prelude_constructors_are_rejected_as_value_bindings(
    tmp_path: Path,
    name: str,
) -> None:
    source = tmp_path / f"invalid_{name.lower()}.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn
def invalid({name}: rust.u64) -> rust.u64:
    return {name}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB210"
    assert "Rust prelude constructor" in diagnostic.message


@pytest.mark.parametrize(
    "source_text",
    [
        """\
from crabwalk import rust
@rust.fn
def invalid(value: rust.u64) -> rust.u64:
    Ok: rust.u64 = value
    return Ok
""",
        """\
from crabwalk import rust
@rust.fn
def invalid() -> rust.u64:
    total: rust.u64 = 0
    for Some in range(1):
        total += Some
    return total
""",
        """\
from crabwalk import rust
@rust.fn
def invalid() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1])
    return values.iter().map(lambda Err: Err).sum()
""",
        """\
from crabwalk import rust
@rust.fn
def invalid(value: rust.u64) -> rust.u64:
    match value:
        case Some:
            return Some
""",
        """\
from crabwalk import rust
@rust.struct
class Invalid:
    Ok: rust.u64
""",
        """\
from crabwalk import rust
@rust.enum
class Invalid:
    Ready = rust.variant(Err=rust.u64)
""",
    ],
)
def test_prelude_constructors_are_rejected_in_all_direct_binding_families(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "invalid_constructor_binding.py"
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB210"


def test_prelude_constructor_spelling_remains_valid_for_qualified_enum_variant(
    tmp_path: Path,
) -> None:
    source = tmp_path / "qualified_variant.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.enum
class Status:
    Ok = rust.variant()

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_qualified_variant")

    assert ir.enums[0].variants[0].name == "Ok"
    assert f"{ir.enums[0].symbol}::Ok" in generated.rust_source


@pytest.mark.parametrize(
    ("factory", "name"),
    [
        ("typevar", "String"),
        ("typevar", "ThreadPool"),
        ("typevar", "Copy"),
        ("typevar", "__CwThreadPool"),
        ("typevar", "__cw_type"),
        ("lifetime", "String"),
        ("lifetime", "__CwLifetime"),
        ("lifetime", "__cw_lifetime"),
    ],
)
def test_generic_names_cannot_shadow_builtin_or_compiler_types(
    tmp_path: Path,
    factory: str,
    name: str,
) -> None:
    source = tmp_path / "invalid_generic_name.py"
    source.write_text(
        (
            "from crabwalk import rust\n"
            f"{name} = rust.{factory}({name!r})\n"
            "@rust.fn\n"
            "def identity(value: rust.u64) -> rust.u64:\n"
            "    return value\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB180"


def test_namespace_policy_constants_cover_generated_prefixes_and_types() -> None:
    assert COMPILER_VALUE_PREFIX == "__cw_"
    assert COMPILER_TYPE_PREFIX == "__Cw"
    assert COMPILER_LIFETIME_PREFIX == "__cw_"
    assert {"String", "Vec", "Result", "ThreadPool"} <= (CRABWALK_BUILTIN_TYPE_NAMES)
    assert is_crabwalk_type_parameter("T")
    assert is_crabwalk_lifetime_parameter("a")


def test_rustc_oracle_accepts_supported_weak_names_in_emitted_positions(
    tmp_path: Path,
) -> None:
    rustc = shutil.which("rustc")
    if rustc is None:
        pytest.skip("rustc is required for the emitted-identifier oracle")
    modules = []
    for name in sorted(RUST_2024_WEAK_KEYWORDS):
        modules.append(
            f"""\
mod oracle_{name} {{
    extern crate core as {name};
    struct Value {{ {name}: u64 }}
    enum Status {{ {name} }}
    trait Behavior {{ fn {name}(&self) -> u64; }}
    impl Value {{ fn {name}(&self) -> u64 {{ self.{name} }} }}
    fn {name}({name}: u64) -> u64 {{ {name} }}
    fn locals() {{
        let {name}: u64 = 1;
        let _ = |{name}: u64| {name};
        match 1u64 {{ {name} => {{ let _ = {name}; }} }}
    }}
    fn generic<{name}>(value: {name}) -> {name} {{ value }}
    fn borrowed<'{name}>(value: &'{name} str) -> &'{name} str {{ value }}
}}
"""
        )
    program = (
        "#![allow(dead_code, non_camel_case_types, non_snake_case, "
        "unused_imports, unused_variables)]\n" + "\n".join(modules)
    )
    result = subprocess.run(
        [
            rustc,
            "--edition=2024",
            "--crate-type=lib",
            "-o",
            str(tmp_path / "identifier_oracle.rlib"),
            "-",
        ],
        input=program,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
