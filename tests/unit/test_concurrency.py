from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


CONCURRENCY_SOURCE = """\
from crabwalk import rust

@rust.fn
def moved_vector_length() -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return rust.spawn(lambda: values.len()).join()

@rust.fn
def channel_value() -> rust.u64:
    pair: rust.Tuple[rust.Sender[rust.u64], rust.Receiver[rust.u64]] = rust.channel(rust.u64)
    sender, receiver = pair
    rust.spawn(lambda: sender.send(42)).join()
    return receiver.recv()

@rust.fn
def shared_counter() -> rust.u64:
    counter: rust.Arc[rust.Mutex[rust.u64]] = rust.Arc(rust.Mutex(0))
    worker_counter: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    rust.spawn(lambda: worker_counter.add_locked(1)).join()
    return counter.get_locked()
"""


def test_threads_channels_and_shared_state_lower_to_std(tmp_path: Path) -> None:
    source = tmp_path / "concurrency.py"
    source.write_text(CONCURRENCY_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_concurrency")

    assert "std::thread::spawn(move || values.len()).join().unwrap()" in (
        generated.rust_source
    )
    assert "std::sync::mpsc::channel::<u64>()" in generated.rust_source
    assert "std::thread::spawn(move || sender.send(42u64).unwrap())" in (
        generated.rust_source
    )
    assert "std::sync::Arc<std::sync::Mutex<u64>>" in generated.rust_source
    assert "std::sync::Arc::new(std::sync::Mutex::new(0u64))" in (generated.rust_source)
    assert "*worker_counter.lock().unwrap() += 1u64" in generated.rust_source
