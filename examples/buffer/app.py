"""Borrow existing Python numeric storage for one native read-only call."""

from array import array

from crabwalk import rust


@rust.fn
def track_plan(
    durations: rust.Buffer[rust.f64],
) -> rust.Tuple[rust.Vec[rust.f64], rust.f64]:
    offsets: rust.Vec[rust.f64] = rust.Vec([])
    elapsed: rust.f64 = 0.0
    for duration in durations.iter():
        offsets.push(elapsed)
        elapsed += duration
    return offsets, elapsed


# Creating this read-only view is constant-time. Crabwalk retains the exporter
# only for the native call and does not construct a second Rust-owned Vec.
storage = array("d", [1.5, 2.0, 3.25])
durations = memoryview(storage).toreadonly()

print(track_plan(durations))
print(track_plan.__crabwalk__["parameter_boundaries"]["durations"])
