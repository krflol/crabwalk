---
type: verification
project: Crabwalk
status: candidate-inventory
updated: 2026-08-21
tags:
  - project/crabwalk
  - verification/release
---

# Crabwalk Alpha Artifact Inventory

## Source-of-truth inputs

| Item | Current location or value |
|---|---|
| Package metadata/version | `pyproject.toml`; `crabwalk 0.0.1` |
| Runtime/compiler sources | `src/crabwalk/` |
| User and release documentation | `README.md`, `Docs/`, `CHANGELOG.md` |
| Tests and benchmark harness | `tests/`, `benchmarks/run_baseline.py` |
| Platform workflow | `.github/workflows/ci.yml` |
| Committable dependency locks | `crabwalk-locks/` |
| IR schema | 4 |
| Code-generation schema | 11 |
| Generated source-map schema | 1 |
| Cache artifact manifest | 1 |
| Embedded wheel manifest | 1 |
| Generated PyO3 dependency | exactly 0.29.2 |

The Python runtime declares no install-time third-party dependency. Its build
backend is `setuptools>=65`. Generated projects use PyO3 and only the Cargo crates
explicitly declared by the analyzed application; demonstration coverage currently
includes regex, Rayon, Serde, and serde_json. The exact transitive dependency and
license inventory must be generated from the release's Python and Cargo locks.

## Required release outputs

- Python sdist and Crabwalk runtime wheel.
- Crabwalk-built application wheels for every advertised CPython/OS pair.
- SHA-256 manifest covering every uploaded file.
- Clean-install logs and native smoke results per artifact.
- Exact source commit/tag, workflow run, Python ABI, Rust/Cargo version, target,
  fingerprint/schema versions, and build command provenance.
- Project license plus generated Python/Cargo dependency license notices.

No publishable artifacts or hashes are claimed by this note yet. Those outputs are
created only after governance/license selection and a green required CI matrix.
This inventory intentionally keeps the corresponding release gate open.
