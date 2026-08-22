"""Chapter 17: native futures, async coordination, and stream-like progress.

The Book uses its teaching ``trpl`` crate for networking and runtime services.
These Crabwalk adaptations keep the examples deterministic and offline while
preserving the important Rust semantics: lazy futures, explicit ``await`` points,
cooperative polling, joining/racing futures, async message flow, and pinning.
"""

from crabwalk import rust


# Rust Book source (async functions, Future values, `.await`, and block_on):
# https://doc.rust-lang.org/book/ch17-01-futures-and-syntax.html
#
# `@rust.async_fn` is native-only. It emits an actual Rust `async fn`; it does not
# create a Python coroutine export. Calling it produces a future, and each Python
# `await` below lowers to Rust's postfix `.await`. The concrete `@rust.fn` wrapper
# marks the one deliberate place where synchronous Python enters the async world.
@rust.async_fn
async def async_double(value: rust.u64) -> rust.u64:
    return value * 2


@rust.async_fn
async def async_pipeline(value: rust.u64) -> rust.u64:
    first: rust.u64 = await async_double(value)
    second: rust.u64 = await async_double(first)
    return second


@rust.fn
def run_async_pipeline(value: rust.u64) -> rust.u64:
    # Crabwalk generates a tiny, safe, std-only executor for this explicit
    # boundary. Production applications can eventually select a full runtime.
    return rust.block_on(async_pipeline(value))


# Rust Book source (cooperatively running multiple futures with join):
# https://doc.rust-lang.org/book/ch17-02-concurrency-with-async.html
#
# A future does work only while an executor polls it. `yield_now` deliberately
# returns Pending once and wakes the task, giving the sibling future a chance to
# make progress. `rust.join` polls both branches fairly and completes only when
# both outputs are ready; its result is a statically typed Rust tuple.
@rust.async_fn
async def yielded_value(value: rust.u64) -> rust.u64:
    await rust.yield_now()
    return value


@rust.async_fn
async def concurrent_sum() -> rust.u64:
    values: rust.Tuple[rust.u64, rust.u64] = await rust.join(
        yielded_value(3),
        yielded_value(4),
    )
    return values[0] + values[1]


@rust.fn
def run_concurrent_sum() -> rust.u64:
    return rust.block_on(concurrent_sum())


# Rust Book sources (selecting the first future and composing a timeout):
# https://doc.rust-lang.org/book/ch17-01-futures-and-syntax.html#racing-two-urls-against-each-other-concurrently
# https://doc.rust-lang.org/book/ch17-03-more-futures.html#building-our-own-async-abstractions
#
# We race deterministic timer futures instead of making the Book's network calls.
# Both branches return u64, so `rust.select` can expose the winner directly. The
# generated combinator polls left first (like the Book's documented unfair select)
# and then right on every pass; the zero-delay right branch wins here.
@rust.async_fn
async def delayed_tag(value: rust.u64, milliseconds: rust.u64) -> rust.u64:
    await rust.sleep_millis(milliseconds)
    return value


@rust.async_fn
async def race_ready_values() -> rust.u64:
    return await rust.select(delayed_tag(10, 5), delayed_tag(20, 0))


@rust.fn
def run_race() -> rust.u64:
    return rust.block_on(race_ready_values())


# Rust Book source (message passing between async activities):
# https://doc.rust-lang.org/book/ch17-02-concurrency-with-async.html#sending-data-between-two-tasks-using-message-passing
#
# The sender and receiver are moved into separate futures. Sending is immediate;
# `recv_async` repeatedly uses nonblocking `try_recv` and yields Pending while the
# channel is empty. Joining the producer and consumer prevents either from being
# dropped early and lets rustc verify ownership of both channel halves.
@rust.async_fn
async def send_two(sender: rust.Sender[rust.u64]) -> None:
    sender.send(10)
    await rust.yield_now()
    sender.send(20)


@rust.async_fn
async def receive_two(receiver: rust.Receiver[rust.u64]) -> rust.u64:
    first: rust.u64 = await receiver.recv_async()
    second: rust.u64 = await receiver.recv_async()
    return first + second


@rust.async_fn
async def async_channel_total() -> rust.u64:
    pair: rust.Tuple[
        rust.Sender[rust.u64],
        rust.Receiver[rust.u64],
    ] = rust.channel(rust.u64)
    sender, receiver = pair
    results: rust.Tuple[None, rust.u64] = await rust.join(
        send_two(sender),
        receive_two(receiver),
    )
    return results[1]


@rust.fn
def run_async_channel() -> rust.u64:
    return rust.block_on(async_channel_total())


# Rust Book sources (streams and the Future/Pin machinery beneath async syntax):
# https://doc.rust-lang.org/book/ch17-04-streams.html
# https://doc.rust-lang.org/book/ch17-05-traits-for-async.html
#
# Crabwalk's first stream adaptation uses an ordinary iterator plus an async yield
# per item. That preserves the chapter's central model—values become available as
# a sequence of future completions—without inventing a Python imitation of Stream.
# Inspect generated Rust to see `Future::poll`, `Poll::{Ready, Pending}`, `Waker`,
# and `pin!`, the exact safe machinery discussed in the following Book section.
@rust.async_fn
async def stream_sequence_sum(values: rust.Vec[rust.u64]) -> rust.u64:
    total: rust.u64 = 0
    for value in values.iter():
        await rust.yield_now()
        total += value
    return total


@rust.fn
def run_stream_sequence() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    return rust.block_on(stream_sequence_sum(values))


# Rust Book source (choosing among futures, tasks, and operating-system threads):
# https://doc.rust-lang.org/book/ch17-06-futures-tasks-threads.html
#
# Chapter 16's `rust.spawn` examples create OS threads. Every helper in this file is
# instead one Future cooperatively driven by the generated executor. Keeping both
# APIs visible makes the Book's final distinction concrete rather than rhetorical.
