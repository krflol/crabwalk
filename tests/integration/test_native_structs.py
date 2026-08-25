from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _create_domain_package(root: Path) -> None:
    package = root / "domain_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        """\
from crabwalk import rust

serde = rust.crate("serde", version="1", features=["derive"])
serde_json = rust.crate("serde_json", version="1")
""",
        encoding="utf-8",
    )
    (package / "model.py").write_text(
        """\
from crabwalk import rust

from . import serde

@rust.struct(derive=[serde.Serialize, serde.Deserialize])
class User:
    id: rust.u64
    name: rust.String

@rust.struct
class Blob:
    data: rust.Vec[rust.u8]
""",
        encoding="utf-8",
    )
    (package / "codec.py").write_text(
        """\
from crabwalk import rust

from . import serde_json
from .model import Blob, User

@rust.fn
def encode(user: rust.Ref[User]) -> rust.String:
    return serde_json.to_string(user).unwrap()

@rust.fn
def user_name(user: rust.Ref[User]) -> rust.String:
    return user.name

@rust.fn
def consume(user: rust.Owned[User]) -> rust.u64:
    return user.id
""",
        encoding="utf-8",
    )
    (package / "app.py").write_text(
        """\
from crabwalk import CrabwalkMoveError

from .codec import consume, encode, user_name
from .model import Blob, User

user = User(id=42, name="Alice")
alias = user
for operation in (
    lambda: User(id=True, name="invalid"),
    lambda: setattr(user, "id", True),
):
    try:
        operation()
    except TypeError as error:
        print("exact-integer", "expected int for rust.u64" in str(error))
blob = Blob(data=b"\\x00\\xff")
print(blob.data, blob.to_python())
print(user.id, user.name)
print(user.to_python())
user.name = "Bob"
print(user_name(user))
print(encode(user))
print(consume(user))
print(user.moved, alias.moved)
try:
    print(alias.name)
except CrabwalkMoveError as error:
    print(type(error).__name__, "moved into consume()" in str(error))
""",
        encoding="utf-8",
    )


def test_struct_derive_fields_serde_and_move_state_are_native(tmp_path: Path) -> None:
    _create_domain_package(tmp_path)
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))

    result = subprocess.run(
        [sys.executable, "-u", "-m", "domain_pkg.app"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "exact-integer True",
        "exact-integer True",
        "b'\\x00\\xff' {'data': b'\\x00\\xff'}",
        "42 Alice",
        "{'id': 42, 'name': 'Alice'}",
        "Bob",
        '{"id":42,"name":"Bob"}',
        "42",
        "True True",
        "CrabwalkMoveError True",
    ]


def test_wide_struct_converts_without_pyo3_tuple_arity_limit(tmp_path: Path) -> None:
    package = tmp_path / "wide_pkg"
    package.mkdir()
    fields = "\n".join(f"    value_{index}: rust.String" for index in range(15))
    arguments = ", ".join(f'value_{index}="{index}"' for index in range(15))
    (package / "__init__.py").write_text(
        f"""\
from crabwalk import rust

@rust.struct
class WideRow:
{fields}

@rust.fn
def first_length(row: rust.Ref[WideRow]) -> rust.usize:
    return row.value_0.len()

row = WideRow({arguments})
print(first_length(row))
print(row.to_python())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))

    result = subprocess.run(
        [sys.executable, "-u", "-c", "import wide_pkg"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "1",
        str({f"value_{index}": str(index) for index in range(15)}),
    ]
