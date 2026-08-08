# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
check-sources.py — find raw sources that are new or changed since last ingest.

One checker, two modes, one comparison rule. Both skills answer the same
question — "what still needs ingesting?" — so they share the same logic and
differ only in where the raw sources and their hashes come from:

    --mode files   raw markdown in Clippings/ etc.; hash = sha256 of the file
    --mode code    files indexed by codegraph; hash = the DB's content_hash

The comparison itself is mode-agnostic. Every Wiki/sources/<page>.md records
the source it was built from and the hash of that source at ingest time:

    source_path: "src/foo/bar.ts"
    source_hash: "a1b2c3..."

We enumerate the current raw sources, look each one up by source_path, and
bucket it:

    new       — no Wiki/sources page references this source_path
    changed   — a page references it, but the hash no longer matches
    unchanged — page exists and hash matches

Change detection is why this replaces the old existence-only checker: a
clipping that was edited, or a code file that was refactored, now surfaces
for re-ingest instead of silently going stale.

Usage:
    uv run check-sources.py <vault> --mode files
    uv run check-sources.py <repo>  --mode code
    uv run check-sources.py <repo>  --mode code --json
    uv run check-sources.py <repo>  --mode code --db /path/to/codegraph.db

--json emits the shape rebuild-index.py --unprocessed consumes:
    {"new": [{"source": ...}], "changed": [{"source": ..., "reason": ...}]}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import yaml

# --- files mode: where raw clippings live, and what to ignore -----------------
RAW_DIRS = ["Clippings", "Twitter-Captures/tools", "Twitter-Captures/articles"]
SKIP_NAMES = {"_index", "README", "bookmarks"}
SKIP_SUFFIXES = ("-template",)

# --- code mode: default location of the codegraph index -----------------------
DEFAULT_DB = ".codegraph/codegraph.db"


def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter of a markdown file as a dict (or {})."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def indexed_sources(vault: Path) -> dict[str, str | None]:
    """Map source_path -> recorded source_hash for every Wiki/sources page.

    A page that predates hashing (no source_hash) maps to None, which the
    caller reports as changed with a distinct reason so a one-time backfill
    is visible rather than mistaken for real drift.
    """
    directory = vault / "Wiki" / "sources"
    out: dict[str, str | None] = {}
    if not directory.is_dir():
        return out
    for page in directory.glob("*.md"):
        fm = parse_frontmatter(page)
        src = fm.get("source_path")
        if src:
            out[str(src)] = fm.get("source_hash")
    return out


def raw_sources_files(vault: Path) -> list[tuple[str, str]]:
    """(source_path, hash) for each raw clipping, source_path vault-relative."""
    out = []
    for d in RAW_DIRS:
        directory = vault / d
        if not directory.is_dir():
            continue
        for f in sorted(directory.glob("*.md")):
            if f.stem in SKIP_NAMES or f.stem.endswith(SKIP_SUFFIXES):
                continue
            out.append((str(f.relative_to(vault)), sha256_file(f)))
    return out


def raw_sources_code(db_path: Path) -> list[tuple[str, str]]:
    """(source_path, content_hash) for each file codegraph has indexed."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT path, content_hash FROM files ORDER BY path").fetchall()
    finally:
        conn.close()
    return [(str(path), str(content_hash)) for path, content_hash in rows]


def classify(indexed: dict[str, str | None], raw: list[tuple[str, str]]):
    new, changed, unchanged = [], [], []
    for source_path, current in raw:
        if source_path not in indexed:
            new.append(source_path)
            continue
        recorded = indexed[source_path]
        if recorded is None:
            changed.append((source_path, "no source_hash recorded (needs backfill)"))
        elif recorded != current:
            changed.append((source_path, "content hash changed since ingest"))
        else:
            unchanged.append(source_path)
    return new, changed, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("vault", nargs="?", default=".")
    parser.add_argument("--mode", choices=["files", "code"], default="files")
    parser.add_argument("--db", help="codegraph db path (code mode; default <vault>/%s)" % DEFAULT_DB)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()

    if not (vault / "Wiki").is_dir():
        print(f"error: {vault / 'Wiki'} not found — is this a wiki root?", file=sys.stderr)
        return 2

    if args.mode == "code":
        db_path = Path(args.db).expanduser().resolve() if args.db else vault / DEFAULT_DB
        if not db_path.exists():
            print(f"error: codegraph index not found at {db_path}", file=sys.stderr)
            print("       run `codegraph index` first, or pass --db", file=sys.stderr)
            return 2
        raw = raw_sources_code(db_path)
    else:
        raw = raw_sources_files(vault)

    new, changed, unchanged = classify(indexed_sources(vault), raw)

    if args.json:
        payload = {
            "mode": args.mode,
            "new": [{"source": s} for s in new],
            "changed": [{"source": s, "reason": r} for s, r in changed],
            "unchanged_count": len(unchanged),
        }
        print(json.dumps(payload, indent=2))
        return 0

    total = len(raw)
    if not new and not changed:
        print(f"Up to date — all {total} {args.mode} source(s) ingested and unchanged.")
        return 0

    print(f"=== {len(new)} new, {len(changed)} changed ({total} total, {len(unchanged)} unchanged) ===\n")
    if new:
        print("New:")
        for s in new:
            print(f"  + {s}")
    if changed:
        if new:
            print()
        print("Changed:")
        for s, r in changed:
            print(f"  ~ {s}  ({r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
