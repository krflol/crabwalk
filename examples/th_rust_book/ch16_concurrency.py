"""Chapter 16: owned threads, channels, and shared-state synchronization."""

from crabwalk import rust


# Rust Book source (`move` closures with threads):
# https://doc.rust-lang.org/book/ch16-01-threads.html#using-move-closures-with-threads
#
# A zero-argument lambda passed to `rust.spawn` always becomes `move || ...`.
# Consequently the Vec is transferred into the native thread and rustc rejects any
# attempted use after that move. `join` returns the closure's statically known type.
@rust.fn
def moved_vector_length() -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return rust.spawn(lambda: values.len()).join()


# Rust Book source (message passing with `mpsc`):
# https://doc.rust-lang.org/book/ch16-02-message-passing.html
#
# `rust.channel(rust.u64)` emits `std::sync::mpsc::channel::<u64>()`. The sender is
# moved into the spawned closure and the receiver stays on the calling thread.
# Send/receive failures unwrap inside Crabwalk's outer panic-containment boundary.
@rust.fn
def channel_value() -> rust.u64:
    pair: rust.Tuple[
        rust.Sender[rust.u64],
        rust.Receiver[rust.u64],
    ] = rust.channel(rust.u64)
    sender, receiver = pair
    rust.spawn(lambda: sender.send(42)).join()
    return receiver.recv()


# Rust Book source (`Arc<Mutex<T>>` shared-state concurrency):
# https://doc.rust-lang.org/book/ch16-03-shared-state.html#atomic-reference-counting-with-arct
#
# `add_locked` deliberately scopes the MutexGuard to one generated expression. The
# worker owns an Arc clone; the original remains available after join. Rust's Send
# and Sync bounds are still checked by rustc for the spawned closure and payload.
@rust.fn
def shared_counter() -> rust.u64:
    counter: rust.Arc[rust.Mutex[rust.u64]] = rust.Arc(rust.Mutex(0))
    worker_counter: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    rust.spawn(lambda: worker_counter.add_locked(1)).join()
    return counter.get_locked()


# Rust Book source (extensible concurrency with Send and Sync):
# https://doc.rust-lang.org/book/ch16-04-extensible-concurrency-sync-and-send.html
#
# Crabwalk does not emulate these marker traits. Compiling the three functions above
# asks rustc to prove the exact same Send/Sync obligations imposed by the standard
# thread, channel, Arc, and Mutex APIs.
