from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from crabwalk.compiler.capabilities import render_capability_markdown  # noqa: E402


START = "<!-- crabwalk-capabilities:start -->"
END = "<!-- crabwalk-capabilities:end -->"


def rendered_document(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    before, separator, remainder = source.partition(START)
    if not separator:
        raise RuntimeError(f"missing {START} in {path}")
    _, separator, after = remainder.partition(END)
    if not separator:
        raise RuntimeError(f"missing {END} in {path}")
    block = f"{START}\n{render_capability_markdown()}\n{END}"
    return f"{before}{block}{after}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "Docs/Crabwalk Language Reference.md",
    )
    options = parser.parse_args()
    expected = rendered_document(options.path)
    current = options.path.read_text(encoding="utf-8")
    if options.check:
        return 0 if current == expected else 1
    options.path.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
