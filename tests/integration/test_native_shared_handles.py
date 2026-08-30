from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_shared_handles import SHARED_SOURCE


@capability_contract("ownership.shared-send-sync")
def test_shared_handle_is_readable_from_many_python_and_rayon_threads(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native_shared.py"
    source.write_text(
        SHARED_SOURCE
        + """
from concurrent.futures import ThreadPoolExecutor
import gc

owned = rust.Vec[SharedRow]([{"value": value} for value in range(1000)])
shared = owned.freeze()
alias = shared.freeze()
print(owned.moved, shared.moved, shared_total.__crabwalk__["gil_released"])
with ThreadPoolExecutor(max_workers=32) as executor:
    results = list(executor.map(lambda _: shared_total(alias), range(128)))
print(len(results), min(results), max(results))
del shared
gc.collect()
print(shared_total(alias))
try:
    shared_panic(alias)
except Exception as error:
    print(type(error).__name__, str(error))
try:
    shared_total(rust.Vec[SharedRow]([{"value": 1}]))
except TypeError as error:
    print("freeze()" in str(error))
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

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
        "True False True",
        "128 499500 499500",
        "499500",
        "CrabwalkPanicError shared panic",
        "True",
    ]


@capability_contract("ownership.shared-send-sync")
def test_shared_handles_survive_reload_gc_and_orderly_interpreter_shutdown(
    tmp_path: Path,
) -> None:
    module = tmp_path / "reload_shared.py"
    module.write_text(SHARED_SOURCE, encoding="utf-8")
    driver = tmp_path / "reload_shared_driver.py"
    updated = SHARED_SOURCE.replace(
        "return rows.par_iter().map(lambda row: row.value).sum()",
        "return rows.par_iter().map(lambda row: row.value).sum() + 0",
        1,
    )
    driver.write_text(
        f"""\
import gc
import importlib
from pathlib import Path
import sys

from crabwalk import rust
import reload_shared

old_total = reload_shared.shared_total
owned = rust.Vec[reload_shared.SharedRow]([{{"value": 2}}, {{"value": 3}}])
shared = owned.freeze()
alias = shared.freeze()
print(old_total(shared))
Path(reload_shared.__file__).write_text({updated!r}, encoding="utf-8")
importlib.invalidate_caches()
reload_shared = importlib.reload(reload_shared)
try:
    reload_shared.shared_total(shared)
except TypeError as error:
    print("different compiled Crabwalk module identity" in str(error))
print(old_total(alias))
del shared
del reload_shared
sys.modules.pop("reload_shared", None)
gc.collect()
print(old_total(alias))
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))
    environment["CRABWALK_PROGRESS"] = "never"

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
    assert result.stdout.splitlines() == ["5", "True", "5", "5"]
