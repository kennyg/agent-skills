#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Find unprocessed raw sources for the LLM wiki.

Usage: uv run check-sources.py [vault-path]
"""

import sys
from pathlib import Path

SKIP_NAMES = {"_index", "README", "bookmarks"}
SKIP_SUFFIXES = {"-template"}
RAW_DIRS = ["Clippings", "Twitter-Captures/tools", "Twitter-Captures/articles"]


def find_raw_sources(vault: Path) -> list[Path]:
    sources = []
    for d in RAW_DIRS:
        p = vault / d
        if not p.is_dir():
            continue
        for f in p.glob("*.md"):
            if f.stem in SKIP_NAMES:
                continue
            if any(f.stem.endswith(s) for s in SKIP_SUFFIXES):
                continue
            sources.append(f)
    return sorted(sources)


def main():
    vault = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    wiki_sources = vault / "Wiki" / "sources"

    if not wiki_sources.is_dir():
        print("Error: Wiki/sources/ not found")
        sys.exit(1)

    indexed = set(f.stem for f in wiki_sources.glob("*.md"))
    raw = find_raw_sources(vault)
    indexed_count = len(indexed)
    raw_count = len(raw)

    if raw_count <= indexed_count:
        print(f"All {raw_count} sources ingested. Wiki is up to date.")
        sys.exit(0)

    # Find new files (newer than index.md)
    index_file = vault / "Wiki" / "index.md"
    index_mtime = index_file.stat().st_mtime if index_file.exists() else 0

    new_files = [f for f in raw if f.stat().st_mtime > index_mtime]
    new_count = raw_count - indexed_count

    print(f"=== {new_count} NEW SOURCE(S) FOUND ===")
    print()
    print(f"Indexed: {indexed_count} | Raw: {raw_count}")
    print()
    if new_files:
        print("New files:")
        for f in new_files:
            print(f"  - {f.relative_to(vault)}")
    print()
    print("Run /wiki-ingest to process them.")


if __name__ == "__main__":
    main()
