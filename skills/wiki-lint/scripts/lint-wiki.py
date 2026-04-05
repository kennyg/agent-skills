#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Health check for an LLM wiki in an Obsidian vault.

Usage: uv run lint-wiki.py [vault-path]
"""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
SKIP_NAMES = {"_index", "README", "bookmarks"}
SKIP_SUFFIXES = {"-template"}
STRUCTURAL = {"index", "log", "overview"}
RAW_DIRS = ["Clippings", "Twitter-Captures/tools", "Twitter-Captures/articles"]


def find_wiki_pages(wiki: Path) -> dict[str, Path]:
    """Map page name -> file path for all wiki .md files."""
    return {f.stem: f for f in wiki.rglob("*.md")}


def find_vault_files(vault: Path) -> set[str]:
    """Set of all vault file stems and relative paths (without .md)."""
    names = set()
    for f in vault.rglob("*.md"):
        names.add(f.stem)
        names.add(str(f.relative_to(vault)).removesuffix(".md"))
    return names


def extract_wikilinks(wiki: Path) -> list[tuple[str, str]]:
    """Extract (link_target, source_file) pairs from all wiki pages."""
    links = []
    for f in wiki.rglob("*.md"):
        text = f.read_text(errors="replace")
        for m in WIKILINK_RE.finditer(text):
            raw = m.group(1)
            target = raw.split("|")[0].split("#")[0].strip()
            if target:
                links.append((target, f.stem))
    return links


def find_raw_sources(vault: Path) -> list[Path]:
    """Find all raw source files."""
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
    return sources


def main():
    vault = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    wiki = vault / "Wiki"

    if not wiki.is_dir():
        print(json.dumps({"error": "Wiki/ not found"}))
        sys.exit(1)

    pages = find_wiki_pages(wiki)
    vault_files = find_vault_files(vault)
    links = extract_wikilinks(wiki)

    # --- Broken wikilinks ---
    link_counts: Counter = Counter()
    broken: set[str] = set()
    for target, source in links:
        # Resolve: wiki page? vault file? basename?
        if target in pages:
            continue
        bname = Path(target).name
        if bname in pages:
            continue
        if target in vault_files:
            continue
        broken.add(target)
        link_counts[target] += 1

    # --- Orphan pages ---
    # Build inbound link map
    inbound: Counter = Counter()
    for target, source in links:
        resolved = target if target in pages else (Path(target).name if Path(target).name in pages else None)
        if resolved and resolved != source:
            inbound[resolved] += 1

    orphans = [p for p in pages if p not in STRUCTURAL and inbound.get(p, 0) == 0]

    # --- Index drift ---
    index_text = (wiki / "index.md").read_text(errors="replace") if (wiki / "index.md").exists() else ""
    drift = [p for p in pages if p not in STRUCTURAL and f"[[{p}]]" not in index_text and f"[[{p}|" not in index_text]

    # --- Unprocessed sources ---
    raw_sources = find_raw_sources(vault)
    indexed_count = len(list((wiki / "sources").glob("*.md"))) if (wiki / "sources").is_dir() else 0
    unprocessed = max(0, len(raw_sources) - indexed_count)

    # --- Missing pages (referenced 2+ times) ---
    multi_ref = {k: v for k, v in link_counts.items() if v >= 2 and k in broken}

    # --- Output ---
    print("=== WIKI LINT REPORT ===")
    print()
    print("## Errors")
    print(f"Broken wikilinks: {len(broken)}")
    for b in sorted(broken):
        print(f"  - {b} ({link_counts[b]}x)")
    print(f"Index drift: {len(drift)}")
    for d in sorted(drift):
        print(f"  - {d}")
    print()
    print("## Warnings")
    print(f"Orphan pages: {len(orphans)}")
    for o in sorted(orphans):
        print(f"  - {o}")
    print(f"Missing pages (referenced 2+ times): {len(multi_ref)}")
    for m in sorted(multi_ref, key=lambda k: -multi_ref[k]):
        print(f"  - {m} ({multi_ref[m]}x)")
    print(f"Unprocessed sources: {unprocessed}")
    print()
    print("## Stats")
    print(f"Total wiki pages: {len(pages)}")
    print(f"Unique wikilinks: {len(set(t for t, _ in links))}")
    print(f"Total wikilink references: {len(links)}")
    print(f"Sources indexed: {indexed_count}")
    print(f"Raw sources: {len(raw_sources)}")


if __name__ == "__main__":
    main()
