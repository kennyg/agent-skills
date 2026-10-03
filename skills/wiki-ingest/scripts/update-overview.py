#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Refresh the counts in `Wiki/overview.md`.

Three places hold counts, and this script rewrites only the numbers in them:

- the intro sentence: "This wiki synthesizes N sources" and the
  "`Clippings/` (A) and `Twitter-Captures/` (B)" split;
- the Status line "**N of M** sources ingested";
- the Status lines for entities, concepts and synthesis pages.

Prose and themes are never touched. The model still decides whether a source
changes the big picture and edits the themes by hand. If the prose around a
count was reworded and a pattern no longer matches, the script says so and
exits 1, so the count cannot drift without a warning.

Usage:
    update-overview.py [--vault DIR] [--check]

`--check` writes nothing and exits 1 when a count is out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if a count is out of date")
    args, vault = wl.parse(parser)

    path = vault / "Wiki" / "overview.md"
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 2
    if args.check:
        text = path.read_text(encoding="utf-8")
        updated, unmatched = ops.rewrite_overview(text, ops.overview_counts(vault))
        changed = updated != text
    else:
        changed, unmatched = ops.write_overview(vault)
    for pattern in unmatched:
        print(f"error: no line in overview.md matches {pattern}", file=sys.stderr)
    if changed:
        print("overview.md counts are out of date" if args.check else "updated overview.md counts")
    elif not unmatched:
        print("overview.md counts are up to date")
    return 1 if unmatched or (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
