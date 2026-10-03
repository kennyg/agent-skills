#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Add `source_hash` to source pages that predate hashing.

A page with a `source_path` and no `source_hash` shows as `changed` in
`check-sources.py`. This script inserts one `source_hash:` line after the
`source_path:` line. It edits the line, not the YAML, so quoting, key order and
comments stay as they are. Pages that already have a hash are skipped.

Usage:
    backfill-hashes.py [--vault DIR] [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args, vault = wl.parse(parser)

    filled = skipped = unresolved = 0
    for page in wl.pages(vault, "sources"):
        if not page.fm:
            continue
        if page.fm.get("source_hash"):
            skipped += 1
            continue
        src = page.fm.get("source_path")
        raw = vault / str(src) if src else None
        if raw is None or not raw.is_file():
            unresolved += 1
            print(f"  ! {page.path.name}: raw source missing ({src})", file=sys.stderr)
            continue
        digest = wl.sha256_file(raw)
        try:
            text = wl.set_frontmatter_value(page.text, "source_hash", wl.quote(digest), after="source_path")
        except ValueError:
            unresolved += 1
            print(f"  ! {page.path.name}: no source_path line to anchor on", file=sys.stderr)
            continue
        if not args.dry_run:
            page.path.write_text(text, encoding="utf-8")
        filled += 1
        print(f"  {'would fill' if args.dry_run else 'filled'} {page.path.name}  {digest[:12]}")

    verb = "would backfill" if args.dry_run else "backfilled"
    print(f"\n{verb} {filled}, skipped {skipped} (already hashed), {unresolved} unresolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
