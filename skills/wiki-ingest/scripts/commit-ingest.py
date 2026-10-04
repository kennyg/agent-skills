#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Commit one ingested source, with a fixed message.

The commit holds only paths under `Wiki/` and the raw source. When ingest
renamed the clipping with `git mv`, the commit holds the rename. Unrelated
vault edits stay out. The script validates the ingest first and refuses to commit when it fails. It
never pushes.

Message format:

    wiki: ingest <slug>

    Source: <raw path>
    SHA-256: <hash>
    Created: <n> entities, <m> concepts
    Updated: <n> entities, <m> concepts

Usage:
    commit-ingest.py [--vault DIR] [--dry-run] SLUG_OR_RAW_PATH
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402

CLIP_DIR = "Clippings"


def message(vault: Path, slug: str) -> str:
    fm = wl.parse_frontmatter(wl.source_page_path(vault, slug))
    found = wl.ingest_summary(vault, slug, str(fm.get("date_ingested")))

    def counts(kind: str) -> str:
        return f"{len(found['entities'][kind])} entities, {len(found['concepts'][kind])} concepts"

    return (
        f"wiki: ingest {slug}\n\n"
        f"Source: {fm.get('source_path')}\n"
        f"SHA-256: {fm.get('source_hash')}\n"
        f"Created: {counts('created')}\n"
        f"Updated: {counts('updated')}\n"
    )


def raw_paths(vault: Path, slug: str) -> list[str]:
    """The raw source path, and its old path when `git mv` staged a rename to it."""
    raw = str(wl.parse_frontmatter(wl.source_page_path(vault, slug)).get("source_path") or "")
    if not raw:
        return []
    paths = [raw]
    staged = wl.git(vault, "diff", "--cached", "--name-status", "-z", "-M", "--diff-filter=R", "--", CLIP_DIR)
    fields = staged.stdout.split("\0") if staged.returncode == 0 else []
    for i in range(0, len(fields) - 2, 3):
        if fields[i + 2] == raw:
            paths.append(fields[i + 1])
    return paths


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("source", help="source page name or raw path")
    parser.add_argument("--dry-run", action="store_true", help="print the message and stop")
    args, vault = wl.parse(parser)
    slug = wl.resolve_slug(vault, args.source)

    report, _ = ops.validate(vault, slug)
    if report.errors:
        print("\n".join(f"error:   {line}" for line in report.errors), file=sys.stderr)
        print("refusing to commit: the ingest does not validate", file=sys.stderr)
        return 1

    text = message(vault, slug)
    if args.dry_run:
        print(text)
        return 0
    paths = ["Wiki", *raw_paths(vault, slug)]
    status = wl.git(vault, "status", "--porcelain", "--", *paths)
    if status.returncode != 0:
        print("error: the vault is not a git repository", file=sys.stderr)
        return 2
    if not status.stdout.strip():
        print("nothing to commit under Wiki/")
        return 0
    # `git add` rejects a path that `git mv` already removed. `git commit` accepts it.
    added = wl.git(vault, "add", "-A", "--", *(p for p in paths if p == "Wiki" or (vault / p).exists()))
    if added.returncode != 0:
        print(added.stderr, file=sys.stderr)
        return added.returncode
    done = wl.git(vault, "commit", "-m", text, "--", *paths)
    print(done.stdout.strip() or done.stderr.strip())
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
