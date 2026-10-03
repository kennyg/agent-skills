#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Run `qmd update` and `qmd embed`, or skip when `qmd` is not installed.

A missing `qmd` is not an error. The script prints one line and exits 0, so an
ingest does not fail on a machine without the search index.

Usage:
    qmd-refresh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def main() -> int:
    wl.make_parser(__doc__).parse_args()
    return ops.refresh_qmd()


if __name__ == "__main__":
    raise SystemExit(main())
