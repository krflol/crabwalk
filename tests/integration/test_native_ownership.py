from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_owned_vec_moves_and_call_scoped_borrows_are_native(tmp_path: Path) -> None:
    other = tmp_path / "other_ownership.py"
    other.write_text(
        """\
from crabwalk import rust

@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()
""",
        encoding="utf-8",
    )
    source = tmp_path / "ownership_app.py"
    source.write_text(
        """\
import builtins
import gc
import importlib.util
import sys
import threading
from copy import copy

from crabwalk import CrabwalkBorrowError, CrabwalkMoveError, CrabwalkThreadError, rust

@rust.fn
def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def append(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)

@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def consume_i64(values: rust.Owned[rust.Vec[rust.i64]]) -> rust.usize:
    return values.len()

@rust.fn
def consume_two(
    first: rust.Owned[rust.Vec[rust.u64]],
    second: rust.Owned[rust.Vec[rust.u64]],
) -> rust.usize:
    return first.len() + second.len()

@rust.fn
def owned_then_ref(
    first: rust.Owned[rust.Vec[rust.u64]],
    second: rust.Ref[rust.Vec[rust.u64]],
) -> rust.usize:
    return first.len() + second.len()

@rust.fn
def consume_three(
    first: rust.Owned[rust.Vec[rust.u64]],
    second: rust.Owned[rust.Vec[rust.u64]],
    third: rust.Owned[rust.Vec[rust.u64]],
) -> rust.usize:
    return first.len() + second.len() + third.len()

@rust.fn
def byte_values() -> rust.Vec[rust.u8]:
    values: rust.Vec[rust.u8] = rust.Vec([])
    values.push(0)
    values.push(255)
    return values

@rust.fn
def conflicting(
    shared: rust.Ref[rust.Vec[rust.u64]],
    mutable: rust.Mut[rust.Vec[rust.u64]],
) -> rust.usize:
    mutable.push(99)
    return shared.len()

@rust.fn
def print_during_mutable_borrow(values: rust.Mut[rust.Vec[rust.u64]]) -> None:
    print(values.len())

@rust.fn
def append_then_consume(
    values: rust.Owned[rust.Vec[rust.u64]], value: rust.u64
) -> rust.usize:
    append(values, value)
    return consume(values)

values = rust.Vec[rust.u64]([1, 2, 3])
alias = values
copied = copy(values)
print(values.rust_type)
print(len(values), total(values))
append(values, 4)
print(values.to_python())
print(alias is values, copied is values)
print(consume(values))
print(values.moved, alias.moved)

for operation in (lambda: len(alias), alias.to_python, lambda: consume(alias)):
    try:
        operation()
    except CrabwalkMoveError as error:
        print(
            type(error).__name__,
            "moved into consume()" in str(error),
            "value created at" in str(error)
            and "consuming parameter defined at" in str(error)
            and "pass rust.Ref or rust.Mut" in str(error),
        )

second = rust.Vec[rust.u64]([5, 6])
print(append_then_consume(second, 7))
print(second.moved)

inferred = rust.Vec([8, 9])
print(rust.to_python(inferred))
print(consume_i64(inferred), inferred.moved)
byte_result = byte_values()
print(type(byte_result).__name__, byte_result)

moved_tail = rust.Vec[rust.u64]([90])
consume(moved_tail)
atomic_first = rust.Vec[rust.u64]([91])
try:
    consume_two(atomic_first, moved_tail)
except CrabwalkMoveError as error:
    print(
        "atomic-owned",
        "second was moved" in str(error),
        error.parameter == "second",
        bool(error.definition_site),
        bool(error.parameter_site),
        bool(error.call_site),
    )
print(atomic_first.moved, atomic_first.to_python())

atomic_ref_first = rust.Vec[rust.u64]([92])
try:
    owned_then_ref(atomic_ref_first, moved_tail)
except CrabwalkMoveError as error:
    print("atomic-ref", "second was moved" in str(error))
print(atomic_ref_first.moved, atomic_ref_first.to_python())

atomic_three_first = rust.Vec[rust.u64]([93])
atomic_three_second = rust.Vec[rust.u64]([94])
try:
    consume_three(atomic_three_first, atomic_three_second, moved_tail)
except CrabwalkMoveError as error:
    print("atomic-three", "third was moved" in str(error))
print(
    atomic_three_first.moved,
    atomic_three_first.to_python(),
    atomic_three_second.moved,
    atomic_three_second.to_python(),
)

converted = rust.from_python([10, 11], rust.Vec[rust.u64])
print(converted.to_python())
for invalid in ([1, -1], [1, True]):
    try:
        rust.from_python(invalid, rust.Vec[rust.u64])
    except Exception as error:
        print(type(error).__name__, "element 1" in str(error))

thread_errors = []
def use_on_other_thread():
    try:
        len(converted)
    except CrabwalkThreadError as error:
        thread_errors.append("thread-affine" in str(error))
thread = threading.Thread(target=use_on_other_thread)
thread.start()
thread.join()
print(thread_errors, converted.to_python())

gc_value = rust.Vec[rust.u64]([12, 13])
gc_alias = gc_value
del gc_value
gc.collect()
print(gc_alias.to_python())

other_path = __file__.replace("ownership_app.py", "other_ownership.py")
spec = importlib.util.spec_from_file_location("other_ownership", other_path)
other_module = importlib.util.module_from_spec(spec)
sys.modules["other_ownership"] = other_module
spec.loader.exec_module(other_module)
foreign = rust.Vec[rust.u64]([30, 31])
try:
    other_module.consume(foreign)
except TypeError as error:
    print("different compiled Crabwalk module identity" in str(error), foreign.to_python())

borrowed = rust.Vec[rust.u64]([20, 21])
try:
    conflicting(borrowed, borrowed)
except CrabwalkBorrowError as error:
    print(
        type(error).__name__,
        "call-scoped" in str(error),
        "parameter 'shared' defined at" in str(error)
        and "parameter 'mutable' defined at" in str(error)
        and "use separate values" in str(error),
        error.parameters == ("shared", "mutable"),
        len(error.parameter_sites) == 2,
        bool(error.call_site),
    )
print(borrowed.to_python())

reentrant_errors = []
reentrant_details = []
real_print = builtins.print
def reentrant_print(value):
    try:
        len(borrowed)
    except Exception as error:
        reentrant_errors.append(type(error).__name__)
        reentrant_details.append(
            "Mut parameter 'values' defined at" in str(error)
            and "call at" in str(error)
        )

builtins.print = reentrant_print
try:
    print_during_mutable_borrow(borrowed)
finally:
    builtins.print = real_print
print(reentrant_errors, reentrant_details)
append(borrowed, 22)
print(borrowed.to_python())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "Vec<u64>",
        "3 3",
        "[1, 2, 3, 4]",
        "True True",
        "4",
        "True True",
        "CrabwalkMoveError True True",
        "CrabwalkMoveError True True",
        "CrabwalkMoveError True True",
        "3",
        "True",
        "[8, 9]",
        "2 True",
        "bytes b'\\x00\\xff'",
        "atomic-owned True True True True True",
        "False [91]",
        "atomic-ref True",
        "False [92]",
        "atomic-three True",
        "False [93] False [94]",
        "[10, 11]",
        "OverflowError True",
        "TypeError True",
        "[True] [10, 11]",
        "[12, 13]",
        "True [30, 31]",
        "CrabwalkBorrowError True True True True True",
        "[20, 21]",
        "['CrabwalkBorrowError'] [True]",
        "[20, 21, 22]",
    ]


def test_rustc_reports_native_use_after_move_at_python_source(tmp_path: Path) -> None:
    source = tmp_path / "use_after_move.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def invalid(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    moved: rust.usize = consume(values)
    return values.len()
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode != 0
    assert "CRAB301 Rust compilation failed" in result.stderr
    assert "borrow of moved value" in result.stderr
    assert "use_after_move.py:10" in result.stderr


def test_source_reload_preserves_old_handle_and_rejects_cross_fingerprint_use(
    tmp_path: Path,
) -> None:
    module = tmp_path / "reload_owned.py"
    module.write_text(
        """\
from crabwalk import rust

@rust.fn
def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()
""",
        encoding="utf-8",
    )
    driver = tmp_path / "reload_driver.py"
    driver.write_text(
        """\
import importlib
from pathlib import Path

from crabwalk import rust
import reload_owned

old = rust.Vec[rust.u64]([1, 2, 3])
print(reload_owned.total(old))

Path(reload_owned.__file__).write_text(
    "from crabwalk import rust\\n\\n"
    "@rust.fn\\n"
    "def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:\\n"
    "    return values.len() + 0\\n",
    encoding="utf-8",
)
importlib.invalidate_caches()
reload_owned = importlib.reload(reload_owned)

try:
    reload_owned.total(old)
except TypeError as error:
    print("different compiled Crabwalk module identity" in str(error))
print(old.to_python())

new = rust.Vec[rust.u64]([4, 5])
print(reload_owned.total(new), new.to_python())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))
    result = subprocess.run(
        [sys.executable, "-u", str(driver)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "3",
        "True",
        "[1, 2, 3]",
        "2 [4, 5]",
    ]


def test_stale_domain_markers_keep_their_compilation_schema(tmp_path: Path) -> None:
    module = tmp_path / "reload_domains.py"
    module.write_text(
        """\
from crabwalk import rust

@rust.struct
class User:
    id: rust.u64

@rust.enum
class State:
    Old = rust.variant()

@rust.fn
def user_id(value: rust.Ref[User]) -> rust.u64:
    return value.id

@rust.fn
def state_score(value: rust.Ref[State]) -> rust.u8:
    match value:
        case State.Old:
            return 1
""",
        encoding="utf-8",
    )
    driver = tmp_path / "reload_domain_driver.py"
    driver.write_text(
        """\
import importlib
from pathlib import Path

import reload_domains

OldUser = reload_domains.User
OldState = reload_domains.State
old_fingerprint = OldUser.compilation_fingerprint
old_user = OldUser(id=1)
old_state = OldState.Old()

Path(reload_domains.__file__).write_text(
    "from crabwalk import rust\\n\\n"
    "@rust.struct\\n"
    "class User:\\n"
    "    id: rust.u64\\n"
    "    name: rust.String\\n\\n"
    "@rust.enum\\n"
    "class State:\\n"
    "    New = rust.variant(code=rust.u8)\\n\\n"
    "@rust.fn\\n"
    "def user_id(value: rust.Ref[User]) -> rust.u64:\\n"
    "    return value.id\\n\\n"
    "@rust.fn\\n"
    "def state_score(value: rust.Ref[State]) -> rust.u8:\\n"
    "    match value:\\n"
    "        case State.New(code=value):\\n"
    "            return value\\n",
    encoding="utf-8",
)
importlib.invalidate_caches()
reload_domains = importlib.reload(reload_domains)

stale_user = OldUser(id=2)
stale_state = OldState.Old()
print(old_user.to_python(), old_state.to_python())
print(stale_user.to_python(), stale_state.to_python())

new_user = reload_domains.User(id=3, name="new")
new_state = reload_domains.State.New(code=7)
print(new_user.to_python(), new_state.to_python())
print(old_fingerprint != reload_domains.User.compilation_fingerprint)

try:
    reload_domains.user_id(stale_user)
except TypeError as error:
    print("different compiled Crabwalk module identity" in str(error))
print(stale_user.to_python())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))

    result = subprocess.run(
        [sys.executable, "-u", str(driver)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "{'id': 1} {'variant': 'Old'}",
        "{'id': 2} {'variant': 'Old'}",
        "{'id': 3, 'name': 'new'} {'variant': 'New', 'code': 7}",
        "True",
        "True",
        "{'id': 2}",
    ]


def test_inferred_owned_values_use_explicit_module_identity_in_both_load_orders(
    tmp_path: Path,
) -> None:
    module_source = """\
from crabwalk import rust

@rust.fn
def consume(values: rust.Ref[rust.Vec[rust.i64]]) -> rust.usize:
    return values.len()

def make(value):
    return rust.Vec([value, value + 1])
"""
    (tmp_path / "owned_a.py").write_text(module_source, encoding="utf-8")
    (tmp_path / "owned_b.py").write_text(module_source, encoding="utf-8")
    driver = tmp_path / "identity_driver.py"
    driver.write_text(
        """\
import importlib
import sys

from crabwalk import rust

for name in sys.argv[1].split(","):
    importlib.import_module(name)

owned_a = importlib.import_module("owned_a")
owned_b = importlib.import_module("owned_b")
first = owned_a.make(1)
second = owned_b.make(3)
print(owned_a.consume(first), first.to_python())
print(owned_b.consume(second), second.to_python())

try:
    rust.Vec([5, 6])
except RuntimeError as error:
    print("ambiguous", "Multiple generated wrappers" in str(error))

explicit = rust.from_python([7, 8], rust.Vec[rust.i64], for_=owned_a.consume)
print("explicit", owned_a.consume(explicit), explicit.to_python())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))
    environment["CRABWALK_PROGRESS"] = "never"

    for order in ("owned_a,owned_b", "owned_b,owned_a"):
        result = subprocess.run(
            [sys.executable, "-u", str(driver), order],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "2 [1, 2]",
            "2 [3, 4]",
            "ambiguous True",
            "explicit 2 [7, 8]",
        ]
