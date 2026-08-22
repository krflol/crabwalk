from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


REGEX_SOURCE = r"""from crabwalk import rust

regex = rust.crate("regex", version="1")

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\d+").unwrap().is_match(value)
"""


def test_static_crate_declaration_generates_cargo_and_rust_paths(
    tmp_path: Path,
) -> None:
    path = tmp_path / "regex_app.py"
    path.write_text(REGEX_SOURCE, encoding="utf-8")
    ir = analyze_path(path, "regex_app")
    generated = generate_project(ir, "_crabwalk_regex_abc")

    assert len(ir.crates) == 1
    assert ir.crates[0].binding == "regex"
    assert ir.crates[0].version == "1"
    assert 'regex = { version = "1" }' in generated.cargo_toml
    assert 'regex::Regex::new(r"' not in generated.rust_source
    assert r'regex::Regex::new("\\d+")' in generated.rust_source
    assert ".unwrap().is_match(value)" in generated.rust_source


def test_crate_options_must_be_static(tmp_path: Path) -> None:
    path = tmp_path / "dynamic.py"
    path.write_text(
        """\
from crabwalk import rust
VERSION = "1"
regex = rust.crate("regex", version=VERSION)

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    assert captured.value.diagnostics[0].code == "CRAB136"


def test_path_git_revision_alias_and_features_generate_exact_cargo_entries(
    tmp_path: Path,
) -> None:
    local = tmp_path / "native"
    local.mkdir()
    path = tmp_path / "dependencies.py"
    path.write_text(
        """\
from crabwalk import rust

local_native = rust.crate("native-core", path="./native", features=["fast"])
remote = rust.crate("remote-core", git="https://example.test/repository.git", rev="abc123")
serde_alias = rust.crate("serde", version="1", features=["derive"])

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    generated = generate_project(analyze_path(path), "_crabwalk_dependencies")
    assert (
        f'local_native = {{ package = "native-core", path = "{local.as_posix()}", '
        'features = ["fast"] }'
    ) in generated.cargo_toml
    assert (
        'remote = { package = "remote-core", '
        'git = "https://example.test/repository.git", rev = "abc123" }'
    ) in generated.cargo_toml
    assert (
        'serde_alias = { package = "serde", version = "1", features = ["derive"] }'
        in generated.cargo_toml
    )
