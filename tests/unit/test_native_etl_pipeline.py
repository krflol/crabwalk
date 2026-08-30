from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


NATIVE_ETL_SOURCE = r"""from crabwalk import rust

@rust.error
class PipelineError:
    Io = rust.from_error(rust.IoError)
    Parse = rust.from_error(rust.String)
    Invalid = rust.variant(message=rust.String)

@rust.fn
def native_etl(input_name: rust.Str, output_name: rust.Str) -> rust.Result[rust.usize, PipelineError]:
    input_path: rust.PathBuf = rust.PathBuf(input_name)
    contents: rust.String = rust.try_(input_path.read_to_string())
    totals: rust.BTreeMap[rust.String, rust.u64] = rust.BTreeMap()
    unique: rust.HashSet[rust.String] = rust.HashSet()
    amounts: rust.Vec[rust.u64] = rust.Vec([])

    for source_line in contents.lines():
        line: rust.Str = source_line.trim()
        if line.is_empty():
            continue
        fields: rust.Vec[rust.String] = line.split("|").map(
            lambda field: rust.String(field.trim())
        ).collect_vec()
        if fields.len() != 3:
            return rust.Err(PipelineError.Invalid(message="expected name|status|amount"))
        if fields[1].as_str() != "active":
            continue
        parsed: rust.Result[rust.u64, rust.String] = fields[2].as_str().parse()
        amount: rust.u64 = rust.try_(parsed)
        unique.insert(fields[0])
        totals.add(fields[0], amount)
        amounts.push(amount)

    amounts.sort_unstable()
    amounts.dedup()
    chunk_count: rust.usize = amounts.as_slice().chunks(2).count()
    window_count: rust.usize = amounts.as_slice().windows(2).count()

    lines: rust.Vec[rust.String] = rust.Vec([])
    for name, total in totals.into_iter():
        rendered_total: rust.String = total.to_string()
        rendered: rust.String = rust.String("")
        rendered.push_str(name.as_str())
        rendered.push_str("|")
        rendered.push_str(rendered_total.as_str())
        lines.push(rendered)

    fixed: rust.String = (1.25).format_fixed(2)
    footer: rust.String = rust.String("scale|")
    footer.push_str(fixed.as_str())
    lines.push(footer)

    separator: rust.String = rust.String("\n")
    output: rust.String = separator.join(lines)
    output.push_str("\n")
    output_path: rust.PathBuf = rust.PathBuf(output_name)
    rust.try_(output_path.write_string(output.as_str()))

    encoded: rust.Vec[rust.u8] = output.into_bytes()
    decoded: rust.String = rust.try_(encoded.into_utf8())
    size: rust.u64 = rust.try_(output_path.metadata_len())
    checked_size: rust.usize = rust.try_(rust.checked_cast(size, rust.usize))
    marker: rust.isize = -1
    if marker == 0:
        return rust.Err(PipelineError.Invalid(message="unreachable marker"))
    return rust.Ok(
        checked_size + unique.len() + chunk_count + window_count + decoded.len()
    )

@rust.fn
def directory_entries(path: rust.Str) -> rust.Result[rust.usize, PipelineError]:
    directory: rust.PathBuf = rust.PathBuf(path)
    entries: rust.Vec[rust.PathBuf] = rust.try_(directory.read_dir())
    return rust.Ok(entries.len())
"""


@capability_contract(
    "etl.native-standard-library",
    "etl.ordered-grouping",
    native=False,
)
def test_native_etl_has_typed_collections_paths_casts_and_formatting(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native_etl.py"
    source.write_text(NATIVE_ETL_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_native_etl")

    assert "std::collections::BTreeMap::new()" in generated.rust_source
    assert "std::collections::HashSet::new()" in generated.rust_source
    assert "std::io::BufReader" in generated.rust_source
    assert "std::io::BufWriter" in generated.rust_source
    assert "TryFrom" in generated.rust_source
    assert 'format!("{:.1$}"' in generated.rust_source
