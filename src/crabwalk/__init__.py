"""Crabwalk's public Python package."""

from . import rust
from ._version import (
    GENERATED_WRAPPER_ABI_VERSION,
    RUNTIME_ABI_VERSION,
    RUNTIME_COMPATIBILITY_SPECIFIER,
    RUNTIME_DISTRIBUTION,
    RUNTIME_DISTRIBUTION_REQUIREMENT,
    __version__,
)
from .diagnostics import (
    CrabwalkBorrowError,
    CrabwalkCompilationError,
    CrabwalkError,
    CrabwalkMoveError,
    CrabwalkPanicError,
    CrabwalkRustError,
    CrabwalkRustErrorSource,
    CrabwalkThreadError,
)
from .embedding import CompiledSource, GeneratedArtifacts, compile_source
from .telemetry import BoundaryTelemetry

__all__ = [
    "CrabwalkCompilationError",
    "CrabwalkBorrowError",
    "CrabwalkError",
    "CrabwalkMoveError",
    "CrabwalkPanicError",
    "CrabwalkRustError",
    "CrabwalkRustErrorSource",
    "CrabwalkThreadError",
    "CompiledSource",
    "GeneratedArtifacts",
    "BoundaryTelemetry",
    "GENERATED_WRAPPER_ABI_VERSION",
    "RUNTIME_ABI_VERSION",
    "RUNTIME_COMPATIBILITY_SPECIFIER",
    "RUNTIME_DISTRIBUTION",
    "RUNTIME_DISTRIBUTION_REQUIREMENT",
    "__version__",
    "compile_source",
    "rust",
]
