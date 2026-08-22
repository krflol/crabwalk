"""Small terminal progress display for implicit decorator-triggered builds."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Literal, TextIO

ProgressMode = Literal["auto", "always", "never"]


class ImplicitBuildProgress:
    """Render an indeterminate build meter without contaminating stdout.

    Interactive terminals receive a single animated line. Redirected stderr gets
    durable phase lines suitable for logs. Set ``CRABWALK_PROGRESS=never`` to
    suppress both, or ``always`` to force output in otherwise quiet environments.
    """

    _SPINNER = ("|", "/", "-", "\\")
    _PULSE = (
        ">.......",
        "=>......",
        "==>.....",
        "===>....",
        "====>...",
        "=====>..",
        "======>.",
        "=======>",
        ".======>",
        "..=====",
        "...====",
        "....===",
        ".....==",
        "......=",
    )

    def __init__(
        self,
        label: str,
        *,
        stream: TextIO | None = None,
        mode: ProgressMode | None = None,
        interval: float = 0.08,
    ) -> None:
        self.label = label
        self.stream = stream or sys.stderr
        self.mode = mode or _progress_mode()
        self.interval = interval
        self.enabled = self.mode != "never"
        self.interactive = bool(
            self.enabled
            and hasattr(self.stream, "isatty")
            and self.stream.isatty()
            and os.environ.get("TERM", "") != "dumb"
        )
        self._phase = "Analyzing Python source"
        self._phase_lock = threading.Lock()
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_plain_phase: str | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self.interactive:
            self._thread = threading.Thread(
                target=self._animate,
                name="crabwalk-progress",
                daemon=True,
            )
            self._thread.start()
        else:
            self._write_plain_phase(self._phase)

    def update(self, phase: str) -> None:
        if not self.enabled:
            return
        with self._phase_lock:
            if phase == self._phase:
                return
            self._phase = phase
        if not self.interactive:
            self._write_plain_phase(phase)

    def finish(self, *, cache_hit: bool, prebuilt: bool = False) -> None:
        detail = "prebuilt" if prebuilt else "cache hit" if cache_hit else "compiled"
        self._complete("ready", detail)

    def fail(self) -> None:
        self._complete("failed", None)

    def _complete(self, state: str, detail: str | None) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.25, self.interval * 3))
        elapsed = time.monotonic() - self._started
        suffix = f", {detail}" if detail else ""
        message = f"Crabwalk {state}: {self.label} ({elapsed:.1f}s{suffix})"
        if self.interactive:
            self.stream.write(
                f"\r\x1b[2K[{'ok' if state == 'ready' else '!!'}] {message}\n"
            )
        else:
            self.stream.write(f"[crabwalk] {message}\n")
        self.stream.flush()

    def _animate(self) -> None:
        frame = 0
        while not self._stop.wait(self.interval):
            with self._phase_lock:
                phase = self._phase
            elapsed = time.monotonic() - self._started
            spinner = self._SPINNER[frame % len(self._SPINNER)]
            pulse = self._PULSE[frame % len(self._PULSE)]
            self.stream.write(
                f"\r\x1b[2K[{spinner}] Crabwalk [{pulse}] {phase}  {elapsed:5.1f}s"
            )
            self.stream.flush()
            frame += 1

    def _write_plain_phase(self, phase: str) -> None:
        if phase == self._last_plain_phase:
            return
        self._last_plain_phase = phase
        elapsed = time.monotonic() - self._started
        self.stream.write(f"[crabwalk] {phase} ({elapsed:.1f}s)\n")
        self.stream.flush()


def _progress_mode() -> ProgressMode:
    value = os.environ.get("CRABWALK_PROGRESS", "auto").strip().lower()
    if value in {"0", "false", "no", "off", "never"}:
        return "never"
    if value in {"1", "true", "yes", "on", "always"}:
        return "always"
    return "auto"
