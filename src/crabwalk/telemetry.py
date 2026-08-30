"""Measured and cardinality-aware Python/native boundary telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import sys


@dataclass(frozen=True, slots=True)
class BoundaryTelemetry:
    """One explicit boundary operation split into observable phases.

    Allocation and clone counts are compiler/runtime-modeled operations, not
    samples from the process allocator. Timings are measured wall-clock
    nanoseconds around the Python validation, native call, and Python output
    normalization phases.
    """

    operation: str
    input_validation_ns: int
    native_ns: int
    output_normalization_ns: int
    input_values: int
    output_values: int
    boundary_crossings: int
    python_container_allocations: int
    native_container_allocations: int
    native_domain_values: int
    native_clones: int
    bytes_copied: int

    @property
    def total_ns(self) -> int:
        return self.input_validation_ns + self.native_ns + self.output_normalization_ns

    def to_dict(self) -> dict[str, int | str]:
        return {**asdict(self), "total_ns": self.total_ns}


def process_rss_bytes() -> int | None:
    """Return current resident bytes using only platform-standard facilities."""

    if sys.platform == "win32":
        return _windows_working_set()
    status = "/proc/self/statm"
    if os.path.isfile(status):
        try:
            with open(status, encoding="ascii") as stream:
                resident_pages = int(stream.read().split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, OSError, ValueError):
        return None


def _windows_working_set() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory_info = psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        get_memory_info.restype = wintypes.BOOL

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = kernel32.GetCurrentProcess()
        if not get_memory_info(process, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    except (AttributeError, OSError, ValueError):
        return None
