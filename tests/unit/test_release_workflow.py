from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)


def test_remote_actions_are_pinned_to_full_commit_shas() -> None:
    remote_uses: list[tuple[Path, str, str]] = []
    for path in WORKFLOWS:
        for action, reference in re.findall(
            r"uses:\s+([^\s@]+)@([^\s#]+)",
            path.read_text(encoding="utf-8"),
        ):
            if action.startswith("./"):
                continue
            remote_uses.append((path, action, reference))

    assert remote_uses
    assert all(
        re.fullmatch(r"[0-9a-f]{40}", reference) for _, _, reference in remote_uses
    ), remote_uses


def test_release_supply_chain_is_pinned_verified_and_attested() -> None:
    ci = WORKFLOWS[0].read_text(encoding="utf-8")
    release = WORKFLOWS[1].read_text(encoding="utf-8")

    assert ci.count("toolchain: 1.97.0") == 3
    assert "pytest==8.4.2" in ci
    assert "build==1.5.0 twine==7.0.0" in release
    assert "pip==26.2.1" in release
    assert release.count("sha256sum --check release/SHA256SUMS") == 4
    assert "uses: actions/attest@" in release
    assert "attestations: write" in release
    assert 'subject-path: "${{ github.workspace }}/release/dist/*"' in release
