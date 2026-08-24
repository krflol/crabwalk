from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import FieldAccessIR, ReturnIR, StructConstructorIR


STRUCT_SOURCE = """\
from crabwalk import rust

@rust.struct
class User:
    id: rust.u64
    name: rust.String

@rust.fn
def user_name(user: rust.Ref[User]) -> rust.String:
    return user.name

@rust.fn
def make_name(identifier: rust.u64) -> rust.String:
    user: User = User(id=identifier, name="Alice")
    return user.name
"""


def test_structs_lower_to_real_rust_and_move_aware_wrapper(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(STRUCT_SOURCE, encoding="utf-8")

    ir = analyze_path(path, "models")

    assert len(ir.structs) == 1
    user = ir.structs[0]
    assert user.name == "User"
    assert [field.name for field in user.fields] == ["id", "name"]
    assert user.type_ref.render() == user.symbol

    returned = ir.functions[0].body[0]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, FieldAccessIR)
    constructed = ir.functions[1].body[0].value
    assert isinstance(constructed, StructConstructorIR)

    generated = generate_project(ir, "_crabwalk_struct_test")
    assert f"struct {user.symbol} {{" in generated.rust_source
    assert "pub id: u64," in generated.rust_source
    assert "pub name: String," in generated.rust_source
    assert (
        f"fn __cw_native_{ir.functions[0].rust_symbol}(user: &{user.symbol}) -> String"
        in generated.rust_source
    )
    assert "return user.name.clone();" in generated.rust_source
    assert (
        f'{user.symbol} {{ id: identifier, name: String::from("Alice") }}'
        in generated.rust_source
    )
    assert f"value: Option<{user.symbol}>" in generated.rust_source
    assert '#[getter("id")]' in generated.rust_source
    assert "fn get_id(&self)" in generated.rust_source
