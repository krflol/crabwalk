from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _write_crate(
    directory: Path,
    package: str,
    rust_source: str,
    *,
    features: tuple[str, ...] = (),
) -> None:
    (directory / "src").mkdir(parents=True)
    feature_lines = "".join(f"{feature} = []\n" for feature in features)
    manifest = (
        "[package]\n"
        f'name = "{package}"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n'
        "publish = false\n\n"
        "[lib]\n"
        'path = "src/lib.rs"\n'
    )
    if feature_lines:
        manifest += f"\n[features]\ndefault = []\n{feature_lines}"
    (directory / "Cargo.toml").write_text(manifest, encoding="utf-8")
    (directory / "src" / "lib.rs").write_text(rust_source, encoding="utf-8")


def test_path_feature_and_pinned_local_git_dependencies_build_and_run(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required for the Git dependency policy fixture")

    path_crate = tmp_path / "path_crate"
    _write_crate(
        path_crate,
        "path-feature-fixture",
        """\
#[cfg(feature = "fast")]
pub fn path_boost(value: u64) -> u64 {
    value + 10
}
""",
        features=("fast",),
    )

    git_crate = tmp_path / "git_crate"
    _write_crate(
        git_crate,
        "git-fixture",
        """\
pub fn git_boost(value: u64) -> u64 {
    value + 100
}
""",
    )
    subprocess.run([git, "init", "-q"], cwd=git_crate, check=True)
    subprocess.run([git, "add", "."], cwd=git_crate, check=True)
    subprocess.run(
        [
            git,
            "-c",
            "user.name=Crabwalk Tests",
            "-c",
            "user.email=crabwalk-tests@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=git_crate,
        check=True,
    )
    revision = subprocess.check_output(
        [git, "rev-parse", "HEAD"],
        cwd=git_crate,
        text=True,
    ).strip()

    source = tmp_path / "dependency_sources.py"
    source.write_text(
        "from crabwalk import rust\n\n"
        'path_dep = rust.crate("path-feature-fixture", path="./path_crate", '
        'features=["fast"])\n'
        f'git_dep = rust.crate("git-fixture", git={json.dumps(git_crate.as_uri())}, '
        f'rev="{revision}")\n\n'
        "@rust.fn\n"
        "def combined(value: rust.u64) -> rust.u64:\n"
        "    return git_dep.git_boost(path_dep.path_boost(value))\n\n"
        "print(combined(1))\n",
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
    assert result.stdout.splitlines() == ["111"]
