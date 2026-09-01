from __future__ import annotations

import hashlib
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _publish_identical_virtual_package(root: str) -> tuple[str, str]:
    from crabwalk.embedding import _materialize_virtual_package

    payload = b"from crabwalk import rust\n"
    sources = {
        "__init__.py": b"",
        "runtime.py": payload,
    }
    package = _materialize_virtual_package(
        Path(root),
        "concurrent_package",
        hashlib.sha256(payload).hexdigest(),
        sources,
    )
    return (
        (package / "__init__.py").read_text(encoding="utf-8"),
        (package / "runtime.py").read_text(encoding="utf-8"),
    )


def test_identical_virtual_package_publication_is_cross_process_safe(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        outcomes = tuple(
            executor.map(
                _publish_identical_virtual_package,
                (str(tmp_path),) * 16,
            )
        )

    assert outcomes == (("", "from crabwalk import rust\n"),) * 16
