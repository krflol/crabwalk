from __future__ import annotations

import os
import sys

import pytest

from crabwalk.build.cargo import CargoBuildCancelled, _run_command
from crabwalk.compiler.capabilities import capability_contract


@capability_contract("build.hard-cancellation", native=False)
def test_cancellable_process_is_terminated_before_return(tmp_path) -> None:
    polls = 0

    def cancelled() -> bool:
        nonlocal polls
        polls += 1
        return polls >= 3

    with pytest.raises(CargoBuildCancelled):
        _run_command(
            (sys.executable, "-c", "import time; time.sleep(60)"),
            tmp_path,
            os.environ.copy(),
            cancelled=cancelled,
        )

    assert polls >= 3
