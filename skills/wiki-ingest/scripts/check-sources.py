#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""List raw sources that need ingest: never ingested, or edited since ingest.

Each raw file in `Clippings/` and `Twitter-Captures/` is matched to a page in
`Wiki/sources/` by `source_path`. A file with no page is `new`. A file whose
SHA-256 differs from the page's `source_hash` is `changed`. The queue lists
each path with its SHA-256, so the hash goes straight into the source page.

A file with no page whose hash equals the `source_hash` of a page with a missing
raw file is `renamed`. It is not in the queue, because the content is already
ingested. The page needs a new `source_path`.

`Twitter-Captures/README.md`, `Twitter-Captures/bookmarks.md`, `_index.md` and
`templates/` are not sources. This script is read-only.

Usage:
    check-sources.py [--vault DIR] [--json] [--exit-code]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402


def git_footer(vault: Path) -> str | None:
    """Count uncommitted files and unpushed commits, or None outside a git repo."""
    status = wl.git(vault, "status", "--porcelain")
    if status.returncode != 0:
        return None
    dirty = len([line for line in status.stdout.splitlines() if line.strip()])
    ahead = wl.git(vault, "rev-list", "--count", "@{upstream}..HEAD")
    pushed = ahead.stdout.strip() if ahead.returncode == 0 else "0"
    return f"uncommitted files: {dirty}   commits not pushed: {pushed}"


def inbox_count(vault: Path) -> int:
    inbox = vault / "Inbox"
    return sum(1 for _ in inbox.rglob("*.md")) if inbox.is_dir() else 0


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--json", action="store_true", help="print the queue as JSON")
    parser.add_argument("--exit-code", action="store_true", help="exit 1 when the queue is not empty")
    args, vault = wl.parse(parser)

    result = wl.classify(vault)
    new, changed, renamed = result["new"], result["changed"], result["renamed"]
    inbox = inbox_count(vault)
    status = 1 if args.exit_code and (new or changed) else 0

    if args.json:
        payload = {
            "new": new,
            "changed": changed,
            "renamed": renamed,
            "unchanged_count": result["unchanged_count"],
            "inbox_notes": inbox,
        }
        print(json.dumps(payload, indent=2))
        return status

    for item in new:
        print(f"new:      {item['source']}  {item['sha256']}")
    for item in changed:
        print(f"changed:  {item['source']}  {item['sha256']}  ->  {item['page']}  ({item['reason']})")
    for item in renamed:
        print(f"renamed:  {item['source']}  <-  {item['was']}  ({item['page']} names the old path)")
    print("---")
    print(f"new sources: {len(new)}   changed sources: {len(changed)}   Inbox notes: {inbox}")
    if renamed:
        print(f"renamed sources: {len(renamed)} (not in the queue; set `source_path` on each page)")
    footer = git_footer(vault)
    if footer:
        print(footer)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
