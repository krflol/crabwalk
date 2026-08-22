"""Chapter 21: a bounded, native Rust HTTP server and thread pool.

The Book's final executable listens forever on port 7878 until its bounded demo
variant has served two requests. A library test must not leave ports or workers
behind, so each Crabwalk call binds an OS-assigned loopback port, serves exactly
one request through the same fixed-size pool design, joins every worker, and
returns the response to Python for assertions.
"""

from crabwalk import rust


# Rust Book sources (binding TCP, reading a request, and writing a response;
# Listings 21-1 through 21-3):
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#listening-to-the-tcp-connection
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#reading-the-request
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#writing-a-response
#
# TcpListener and TcpStream are concrete std::net values in generated Rust. Port
# zero asks the OS for an unused port; local_port reads it back before the listener
# is moved into a Send + 'static worker job. The client writes an ordinary HTTP/1.1
# request, half-closes its write side, and reads until the server closes the stream.


# Rust Book sources (real HTML, routing, 404, and refactoring; Listings 21-4
# through 21-9):
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#returning-real-html
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#validating-the-request-and-selectively-responding
# https://doc.rust-lang.org/book/ch21-01-single-threaded.html#refactoring
#
# hello.html and 404.html beside this module reproduce the Book's source assets.
# Their compact equivalents are embedded below so a built wheel does not depend on
# the process working directory. `serve_http_once` factors the differing status and
# body selection from the shared Content-Length/Connection response construction.
HELLO_BODY = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    "<title>Hello!</title></head><body><h1>Hello!</h1>"
    "<p>Hi from Rust</p></body></html>"
)
NOT_FOUND_BODY = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    "<title>Hello!</title></head><body><h1>Oops!</h1>"
    "<p>Sorry, I don't know what you're asking for.</p></body></html>"
)


@rust.fn
def http_round_trip(path: rust.Str) -> rust.String:
    listener: rust.TcpListener = rust.TcpListener("127.0.0.1:0")
    port: rust.u64 = listener.local_port()
    pool: rust.ThreadPool = rust.ThreadPool(4)

    # rust.drop turns the handler's status-code result into a unit-returning Job.
    # Generated execute() boxes this closure as `dyn FnOnce() + Send + 'static`.
    pool.execute(
        lambda: rust.drop(
            listener.serve_http_once(
                '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Hello!</title></head><body><h1>Hello!</h1><p>Hi from Rust</p></body></html>',
                '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Hello!</title></head><body><h1>Oops!</h1><p>Sorry, I don\'t know what you\'re asking for.</p></body></html>',
            )
        )
    )

    client: rust.TcpStream = rust.TcpStream(port)
    client.write_get(path)
    client.shutdown_write()
    response: rust.String = client.read_to_string()

    # finish() closes the sender, joins every worker, and reports a captured job
    # panic explicitly. Drop repeats only a non-panicking no-op cleanup path.
    pool.finish().expect("HTTP worker failed")
    return response


# Rust Book sources (slow requests and evolving a finite thread pool; Listings
# 21-10 through 21-21):
# https://doc.rust-lang.org/book/ch21-02-multithreaded.html#simulating-a-slow-request
# https://doc.rust-lang.org/book/ch21-02-multithreaded.html#improving-throughput-with-a-thread-pool
#
# `/sleep` executes the Book's delayed branch with 50 ms instead of five seconds,
# keeping the ordering behavior observable without making the suite needlessly
# slow. The generated __CwThreadPool follows the compiler-driven sequence's final
# shape: Vec<Worker>, mpsc::Sender<Job>, Arc<Mutex<Receiver<Job>>>, and boxed jobs.
@rust.fn
def thread_pool_job_total() -> rust.u64:
    counter: rust.Arc[rust.Mutex[rust.u64]] = rust.Arc(rust.Mutex(0))
    first: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    second: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    third: rust.Arc[rust.Mutex[rust.u64]] = counter.clone()
    pool: rust.ThreadPool = rust.ThreadPool(2)
    pool.execute(lambda: first.add_locked(1))
    pool.execute(lambda: second.add_locked(1))
    pool.execute(lambda: third.add_locked(1))
    pool.finish().expect("thread pool worker failed")
    return counter.get_locked()


# Rust Book source (rejecting a zero-sized pool; Listing 21-13):
# https://doc.rust-lang.org/book/ch21-02-multithreaded.html#validating-the-number-of-threads-in-new
#
# The assert lives in native ThreadPool::new. Passing zero crosses Crabwalk's panic
# containment boundary as CrabwalkPanicError rather than unwinding into CPython.
@rust.fn
def validated_pool_size(size: rust.usize) -> rust.usize:
    pool: rust.ThreadPool = rust.ThreadPool(size)
    pool.finish().expect("thread pool worker failed")
    return size


# Rust Book sources (Drop, disconnect signaling, and bounded shutdown; Listings
# 21-22 through 21-25):
# https://doc.rust-lang.org/book/ch21-03-graceful-shutdown-and-cleanup.html#implementing-the-drop-trait-on-threadpool
# https://doc.rust-lang.org/book/ch21-03-graceful-shutdown-and-cleanup.html#signaling-to-the-threads-to-stop-listening-for-jobs
#
# The generated finish implementation takes and drops Option<Sender<Job>>, drains
# the workers, joins each thread, and returns the first caught worker failure.
# Drop uses the same shutdown path but never propagates a panic. Channel FIFO
# ordering means queued jobs run before disconnection; thread_pool_job_total reads
# the counter only after finish.
# The end-to-end runner sends successful, missing, and delayed requests, providing
# the bounded cleanup proof without an externally managed background process.
