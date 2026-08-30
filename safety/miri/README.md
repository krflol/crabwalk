# Crabwalk generated-unsafe Miri fixture

This standalone crate mirrors the atomic counter, guarded C `abs` precondition,
and non-panicking worker-join contracts emitted by Crabwalk. CI runs it under
Miri on a pinned nightly toolchain; stable `cargo test` remains a fast local
smoke check. The fixture deliberately contains no PyO3 or platform FFI so Miri
can examine the memory/concurrency invariants directly.
