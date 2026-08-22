---
type: verification
project: Crabwalk
status: baseline-harness-ready
updated: 2026-08-21
tags:
  - project/crabwalk
  - verification/performance
---

# Crabwalk Performance Baseline

The repeatable harness is `benchmarks/run_baseline.py`. It creates an isolated
source project, records a cold Cargo build and unchanged second-process cache hit,
then measures primitive call overhead, a native loop against Python's equivalent,
and explicit `Vec[u64]` conversion in both directions.

```powershell
python benchmarks/run_baseline.py > baseline.json
```

## Interpretation rules

- Timing is not native-execution evidence; the ABI/tracing/generated-code tests are.
- Compare like-for-like OS, CPU, power mode, Python, Rust, linker, and cache state.
- Preserve raw JSON as a CI artifact rather than copying one noisy run into a claim.
- Establish warning/failure budgets only after at least 10 CI samples per platform.
- Cold build, cached process, primitive call, native work, and conversion metrics
  receive separate budgets; one aggregate number would hide regressions.

## Provisional budget policy

Until repeated CI data exists, performance changes are reported but do not fail the
build. Promotion of PERF-001 requires median and p95 baselines per advertised OS,
with a documented noise margin. Correctness, cache verification, and ABI safety
remain hard gates regardless of speed.

## Local smoke sample

One post-optimization Windows/CPython 3.11.8 sample on 2026-08-21 recorded:

| Metric | Cold process | Valid cache-hit process |
|---|---:|---:|
| Process wall time | 15.93 s | 0.40 s |
| Decorator/build-or-load time | 15.65 s | 0.21 s |
| Primitive call | 2.74 µs | 1.22 µs |
| Native sum over 2,000,000 integers | 1.38 ms | 0.50 ms |
| Python `sum(range(...))` | 41.60 ms | 34.15 ms |
| Python list → `Vec[u64]` (100,000) | 22.32 ms | 20.13 ms |
| `Vec[u64]` → Python list (100,000) | 1.10 ms | 1.50 ms |

This sample is diagnostic, not a release budget. It caught and removed an accidental
per-call filesystem path resolution: cached primitive overhead fell from roughly
170 µs to 1.22 µs in the same harness. Retain the raw JSON in future CI runs.

See [[Docs/Crabwalk Compatibility and Verification]] for the evidence hierarchy.
