#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
backfill-hashes.py — add source_hash to Wiki/sources pages that predate it.

A wiki built before change-detection has source pages with a source_path but
no source_hash. Under the new checker every such page reports as "changed"
(reason: no source_hash recorded) until it's stamped once. This computes the
current hash for each and inserts it, so the next check-sources run sees them
as unchanged instead of a wall of false positives.

It edits frontmatter surgically — inserting a single `source_hash:` line after
`source_path:` — rather than reserialising the YAML, so quoting, key order,
and comments in your pages are left untouched. Pages that already have a
source_hash are skipped.

Usage:
    uv run backfill-hashes.py <vault> --mode files
    uv run backfill-hashes.py <repo>  --mode code
    uv run backfill-hashes.py <vault> --mode files --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

import yaml

DEFAULT_DB = ".codegraph/codegraph.db"
SOURCE_PATH_RE = re.compile(r"(?m)^([ \t]*)source_path([ \t]*:.*)$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def code_hashes(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {p: h for p, h in conn.execute("SELECT path, content_hash FROM files")}
    finally:
        conn.close()


def frontmatter(text: str):
    """Return (fm_dict, fm_text, body) or None if there is no frontmatter."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data, parts[1], parts[2]


def insert_hash(fm_text: str, digest: str) -> str | None:
    """Insert a source_hash line right after source_path; None if no anchor."""
    def repl(m: re.Match) -> str:
        return f'{m.group(0)}\n{m.group(1)}source_hash: "{digest}"'
    new_text, n = SOURCE_PATH_RE.subn(repl, fm_text, count=1)
    return new_text if n else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("vault", nargs="?", default=".")
    parser.add_argument("--mode", choices=["files", "code"], default="files")
    parser.add_argument("--db", help="codegraph db path (code mode)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    sources_dir = vault / "Wiki" / "sources"
    if not sources_dir.is_dir():
        print(f"error: {sources_dir} not found", file=sys.stderr)
        return 2

    db_map: dict[str, str] = {}
    if args.mode == "code":
        db_path = Path(args.db).expanduser().resolve() if args.db else vault / DEFAULT_DB
        if not db_path.exists():
            print(f"error: codegraph index not found at {db_path}", file=sys.stderr)
            print(f"       run `codegraph init --index {vault}` first, or pass --db", file=sys.stderr)
            return 2
        db_map = code_hashes(db_path)

    filled = skipped = missing = 0
    for page in sorted(sources_dir.glob("*.md")):
        parsed = frontmatter(page.read_text(encoding="utf-8"))
        if parsed is None:
            continue
        fm, fm_text, body = parsed
        if fm.get("source_hash"):
            skipped += 1
            continue
        src = fm.get("source_path")
        if not src:
            missing += 1
            print(f"  ! {page.name}: no source_path", file=sys.stderr)
            continue
        if args.mode == "files":
            raw = vault / str(src)
            if not raw.exists():
                missing += 1
                print(f"  ! {page.name}: raw source missing ({src})", file=sys.stderr)
                continue
            digest = sha256_file(raw)
        else:
            digest = db_map.get(str(src), "")
            if not digest:
                missing += 1
                print(f"  ! {page.name}: {src} not in index", file=sys.stderr)
                continue

        new_fm = insert_hash(fm_text, digest)
        if new_fm is None:
            missing += 1
            print(f"  ! {page.name}: could not anchor to source_path line", file=sys.stderr)
            continue
        if not args.dry_run:
            page.write_text("---" + new_fm + "---" + body, encoding="utf-8")
        filled += 1
        print(f"  {'would fill' if args.dry_run else 'filled'} {page.name}  {digest[:12]}")

    verb = "would backfill" if args.dry_run else "backfilled"
    print(f"\n{verb} {filled}, skipped {skipped} (already hashed), {missing} unresolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
