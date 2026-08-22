from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


ASYNC_SOURCE = """\
from crabwalk import rust

@rust.async_fn
async def async_double(value: rust.u64) -> rust.u64:
    return value * 2

@rust.async_fn
async def async_pipeline(value: rust.u64) -> rust.u64:
    first: rust.u64 = await async_double(value)
    second: rust.u64 = await async_double(first)
    return second

@rust.fn
def run_pipeline(value: rust.u64) -> rust.u64:
    return rust.block_on(async_pipeline(value))

@rust.async_fn
async def yielded(value: rust.u64) -> rust.u64:
    await rust.yield_now()
    return value

@rust.async_fn
async def joined_total() -> rust.u64:
    values: rust.Tuple[rust.u64, rust.u64] = await rust.join(yielded(3), yielded(4))
    return values[0] + values[1]

@rust.fn
def run_joined_total() -> rust.u64:
    return rust.block_on(joined_total())

@rust.async_fn
async def delayed(value: rust.u64, milliseconds: rust.u64) -> rust.u64:
    await rust.sleep_millis(milliseconds)
    return value

@rust.async_fn
async def selected_value() -> rust.u64:
    return await rust.select(delayed(10, 5), delayed(20, 0))

@rust.fn
def run_selected_value() -> rust.u64:
    return rust.block_on(selected_value())

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
async def channel_total() -> rust.u64:
    pair: rust.Tuple[rust.Sender[rust.u64], rust.Receiver[rust.u64]] = rust.channel(rust.u64)
    sender, receiver = pair
    results: rust.Tuple[None, rust.u64] = await rust.join(send_two(sender), receive_two(receiver))
    return results[1]

@rust.fn
def run_channel_total() -> rust.u64:
    return rust.block_on(channel_total())
"""


def test_async_helpers_lower_to_native_futures_and_std_executor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "async_native.py"
    source.write_text(ASYNC_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_async_native")

    first, pipeline, wrapper = ir.functions[:3]
    assert first.is_async is True
    assert first.exported is False
    assert pipeline.is_async is True
    assert pipeline.exported is False
    assert wrapper.is_async is False
    assert wrapper.exported is True
    functions = {function.name: function.rust_symbol for function in ir.functions}
    assert "impl std::task::Wake for __CwNoopWake" in generated.rust_source
    assert "fn __cw_block_on<F: std::future::Future>" in generated.rust_source
    assert f"async fn __cw_native_{functions['async_double']}(value: u64) -> u64" in (
        generated.rust_source
    )
    assert (
        f"__cw_native_{functions['async_double']}(value).await" in generated.rust_source
    )
    assert f"__cw_block_on(__cw_native_{functions['async_pipeline']}(value))" in (
        generated.rust_source
    )
    assert (
        f"__cw_join2(__cw_native_{functions['yielded']}(3u64), "
        f"__cw_native_{functions['yielded']}(4u64)).await"
    ) in (generated.rust_source)
    assert f"__cw_select2(__cw_native_{functions['delayed']}(10u64, 5u64), " in (
        generated.rust_source
    )
    assert "__cw_recv_async(&receiver).await" in generated.rust_source
    assert "return (values.0 + values.1);" in generated.rust_source
    assert f"wrap_pyfunction!({functions['async_double']}" not in generated.rust_source
    assert f"wrap_pyfunction!({functions['run_pipeline']}, m)" in generated.rust_source
