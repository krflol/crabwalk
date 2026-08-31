from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract


@capability_contract("embedding.nonexecuting-source-callable")
def test_source_compiles_and_binds_without_python_module_execution(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "run_embedding.py"
    sentinel = tmp_path / "top-level-executed.txt"
    source_cache = tmp_path / "source-cache"
    authored_source = f"""\
from pathlib import Path
Path({str(sentinel)!r}).write_text("executed", encoding="utf-8")

from crabwalk import rust

@rust.fn
def normalize(name: rust.Str) -> rust.String:
    return name.to_lowercase()
"""
    runner.write_text(
        f"""\
import json
from pathlib import Path

from crabwalk import compile_source

source = {authored_source!r}
phases = []
compiled = compile_source(
    source,
    filename="recipe.py",
    cache_directory=Path({str(source_cache)!r}),
    progress=phases.append,
)
normalize = compiled.function("normalize")
print(normalize("CrabWalk"))
print(Path({str(sentinel)!r}).exists())
print(json.dumps(normalize.__crabwalk__["parameter_boundaries"]["name"], sort_keys=True))
print(phases.count("Analyzing Python source"))
print(compiled.functions)
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

    result = subprocess.run(
        [sys.executable, "-u", str(runner)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "crabwalk"
    assert lines[1] == "False"
    boundary = json.loads(lines[2])
    assert boundary == {
        "allocation": "Borrowed",
        "borrowed": True,
        "copies_elements": False,
        "input_policy": "String",
        "lifetime": "native call",
        "ownership": "Borrow",
        "rust_type": "rust.Str",
    }
    assert lines[3] == "1"
    assert lines[4] == "('normalize',)"


@capability_contract("embedding.virtual-package", native=True)
def test_virtual_package_compiles_cross_module_calls_without_execution(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "run_virtual_embedding.py"
    sentinel = tmp_path / "virtual-executed.txt"
    deep_cache = tmp_path / ("deep-embedding-root-" * 5) / "cache"
    sources = {
        "__init__.py": (
            f"from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed')\n"
            "from .kernel import triple\n"
        ),
        "kernel.py": """\
from crabwalk import rust
from .support import add_one

@rust.fn
def triple(value: rust.u64) -> rust.u64:
    return add_one(value) * 3
""",
        "support.py": """\
from crabwalk import rust

@rust.fn
def add_one(value: rust.u64) -> rust.u64:
    return value + 1
""",
    }
    runner.write_text(
        f"""\
from crabwalk import compile_source

compiled = compile_source(
    {sources!r},
    module_name="virtual_recipe",
    entry="kernel.py",
    cache_directory={str(deep_cache)!r},
)
print(compiled.function("kernel.triple")(4))
print({str(sentinel)!r})
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"
    result = subprocess.run(
        [sys.executable, "-u", str(runner)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "15"
    assert not sentinel.exists()
