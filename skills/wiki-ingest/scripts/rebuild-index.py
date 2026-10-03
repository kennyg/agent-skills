#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Regenerate the `Wiki/index.md` tables from page frontmatter.

Prose outside the marker fences is kept. Each table sits between a pair of
markers and is rewritten on every run:

    <!-- BEGIN:sources -->  ...  <!-- END:sources -->
    <!-- BEGIN:entities -->, concepts, synthesis, unprocessed

A missing fence is added under its own heading on the first run. A legacy
hand-written table under a matching heading is replaced in place.

The Unprocessed table comes from the same queue that `check-sources.py` prints.

Usage:
    rebuild-index.py [--vault DIR] [--dry-run] [--check]

`--check` writes nothing and exits 1 when `Wiki/index.md` is out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the new index instead of writing it")
    parser.add_argument("--check", action="store_true", help="exit 1 if the index is out of date")
    args, vault = wl.parse(parser)

    current, text = ops.render_index(vault)
    if args.check:
        print("index.md is out of date" if text != current else "index.md is up to date")
        return 1 if text != current else 0
    if args.dry_run:
        print(text)
        return 0
    changed = ops.write_index(vault)
    counts = ", ".join(f"{len(wl.pages(vault, f))} {f}" for f in wl.FOLDER_TYPE)
    print(f"{'Rebuilt' if changed else 'Unchanged'} Wiki/index.md - {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
