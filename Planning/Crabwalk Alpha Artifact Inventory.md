---
type: verification
project: Crabwalk
status: release-preflight
updated: 2026-08-22
tags:
  - project/crabwalk
  - verification/release
---

# Crabwalk 1.0.0 Artifact Inventory

## Source-of-truth inputs

| Item | Current location or value |
|---|---|
| Package metadata/version | `pyproject.toml`; `crabwalk 1.0.0` |
| Project license | `Apache-2.0`; canonical text in `LICENSE` |
| Governance and security | `GOVERNANCE.md`, `SECURITY.md` |
| Cross-platform hardening evidence | GitHub Actions run `32594114165`; nine jobs passed |
| Runtime/compiler sources | `src/crabwalk/` |
| User and release documentation | `README.md`, `Docs/`, `CHANGELOG.md` |
| Tests and benchmark harness | `tests/`, `benchmarks/run_baseline.py` |
| Platform workflow | `.github/workflows/ci.yml` |
| Committable dependency locks | `crabwalk-locks/` |
| Build-fingerprint schema | 4 |
| IR schema | 18 |
| Code-generation schema | 31 |
| Generated source-map schema | 1 |
| Cache artifact manifest | 1 |
| Embedded wheel manifest | 2 |
| Runtime ABI | 1 |
| Generated PyO3 dependency | exactly 0.29.2 |

The Python runtime declares no install-time third-party dependency. Its build
backend is `setuptools>=77.0.3`. Generated projects use PyO3 and only the Cargo crates
explicitly declared by the analyzed application; demonstration coverage currently
includes regex, Rayon, Serde, and serde_json. The exact transitive dependency and
license inventory must be generated from the release's Python and Cargo locks.

## Release outputs

- `crabwalk-1.0.0.tar.gz` Python source distribution.
- `crabwalk-1.0.0-py3-none-any.whl` Python runtime wheel.
- `SHA256SUMS` covering every GitHub release artifact.
- Clean-install metadata/CLI/import smoke results for both distribution formats.
- Exact source commit, `v1.0.0` tag, workflow run, schema versions, and build
  command provenance.
- Apache-2.0 license metadata and canonical license file in both archives.

Artifact sizes, hashes, final commit/tag, workflow URL, and clean-install evidence
are filled in only after the immutable archives are built. This note does not claim
those values before the final matrix and artifact verification complete.
