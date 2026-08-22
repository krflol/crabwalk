from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


WEB_SERVER_SOURCE = r"""\
from crabwalk import rust

@rust.fn
def http_round_trip(path: rust.Str) -> rust.String:
    listener: rust.TcpListener = rust.TcpListener("127.0.0.1:0")
    port: rust.u64 = listener.local_port()
    server: rust.ThreadHandle[rust.u64] = rust.spawn(
        lambda: listener.serve_http_once(
            "<h1>Hello!</h1><p>Hi from Rust</p>",
            "<h1>Oops!</h1><p>Not found.</p>",
        )
    )
    client: rust.TcpStream = rust.TcpStream(port)
    client.write_get(path)
    client.shutdown_write()
    response: rust.String = client.read_to_string()
    server.join()
    return response

@rust.fn
def thread_pool_jobs() -> rust.u64:
    counter: rust.Arc[rust.Mutex[rust.u64]] = rust.Arc(rust.Mutex(0))
    first: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    second: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    third: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    pool: rust.ThreadPool = rust.ThreadPool(2)
    pool.execute(lambda: first.add_locked(1))
    pool.execute(lambda: second.add_locked(1))
    pool.execute(lambda: third.add_locked(1))
    rust.drop(pool)
    return counter.get_locked()
"""


def test_tcp_and_thread_pool_lower_to_standard_library_rust(tmp_path: Path) -> None:
    source = tmp_path / "web_server.py"
    source.write_text(WEB_SERVER_SOURCE, encoding="utf-8")

    generated = generate_project(analyze_path(source), "_crabwalk_web_server")
    rust_source = generated.rust_source

    assert "std::net::TcpListener::bind" in rust_source
    assert "std::net::TcpStream::connect" in rust_source
    assert "std::io::Read::read_to_string" in rust_source
    assert "std::io::Write::write_all" in rust_source
    assert 'format!("GET {} HTTP/1.1' in rust_source
    assert "HTTP/1.1 404 NOT FOUND" in rust_source
    assert "type __CwJob = Box<dyn FnOnce() + Send + 'static>" in rust_source
    assert "struct __CwThreadPool" in rust_source
    assert "std::sync::mpsc::channel()" in rust_source
    assert "impl Drop for __CwThreadPool" in rust_source
    assert "drop(self.sender.take())" in rust_source
    assert "worker.thread.join().unwrap()" in rust_source
    assert "pool.execute(move ||" in rust_source
