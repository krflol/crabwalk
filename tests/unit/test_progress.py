from io import StringIO

from crabwalk.progress import ImplicitBuildProgress


def test_redirected_progress_is_durable_plain_text() -> None:
    stream = StringIO()
    progress = ImplicitBuildProgress("demo", stream=stream, mode="always")

    progress.start()
    progress.update("Compiling the Rust extension")
    progress.finish(cache_hit=False)

    output = stream.getvalue()
    assert "[crabwalk] Analyzing Python source" in output
    assert "[crabwalk] Compiling the Rust extension" in output
    assert "Crabwalk ready: demo" in output
    assert "compiled" in output


def test_progress_can_be_disabled_for_ci() -> None:
    stream = StringIO()
    progress = ImplicitBuildProgress("demo", stream=stream, mode="never")

    progress.start()
    progress.update("Compiling the Rust extension")
    progress.finish(cache_hit=True)

    assert stream.getvalue() == ""
