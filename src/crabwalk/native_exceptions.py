"""Private exception names shared by generated extensions and the runtime.

The generated module exposes these classes only so the Python runtime can
translate native failures by exception identity.  They are deliberately not
part of Crabwalk's public API.
"""

from __future__ import annotations

NATIVE_MOVE_ERROR = "_CrabwalkNativeMoveError"
NATIVE_BORROW_ERROR = "_CrabwalkNativeBorrowError"
NATIVE_PANIC_ERROR = "_CrabwalkNativePanicError"
NATIVE_RUST_RESULT_ERROR = "_CrabwalkNativeRustResultError"

NATIVE_EXCEPTION_NAMES = (
    NATIVE_MOVE_ERROR,
    NATIVE_BORROW_ERROR,
    NATIVE_PANIC_ERROR,
    NATIVE_RUST_RESULT_ERROR,
)
