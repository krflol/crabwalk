from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


SMART_POINTER_SOURCE = """\
from crabwalk import rust

@rust.fn
def boxed_value(value: rust.u64) -> rust.u64:
    boxed: rust.Box[rust.u64] = rust.Box(value)
    return boxed.deref_copy()

@rust.fn
def rc_counts() -> rust.usize:
    original: rust.Rc[rust.u64] = rust.Rc(5)
    shared_copy: rust.Rc[rust.u64] = original.clone()
    before: rust.usize = original.strong_count()
    rust.drop(shared_copy)
    after: rust.usize = original.strong_count()
    return before * 10 + after

@rust.fn
def interior_mutation() -> rust.u64:
    cell: rust.RefCell[rust.u64] = rust.RefCell(5)
    old: rust.u64 = cell.replace(10)
    return old + cell.borrow_copy()
"""


def test_smart_pointer_operations_lower_to_standard_rust_types(tmp_path: Path) -> None:
    source = tmp_path / "smart_pointers.py"
    source.write_text(SMART_POINTER_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_smart_pointers")

    assert "let boxed: Box<u64> = Box::new(value);" in generated.rust_source
    assert "let original: std::rc::Rc<u64> = std::rc::Rc::new(5u64);" in (
        generated.rust_source
    )
    assert "std::rc::Rc::strong_count(&original)" in generated.rust_source
    assert "std::mem::drop(shared_copy);" in generated.rust_source
    assert "std::cell::RefCell<u64>" in generated.rust_source
    assert "cell.replace(10u64)" in generated.rust_source
    assert "*cell.borrow()" in generated.rust_source
