#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Create the `Wiki/sources/<slug>.md` skeleton for one raw source.

The script fills every field a person should not type: the slug, `source_path`,
`source_hash`, `source_url`, `author` and `date_ingested`. It leaves the
summary, the key claims and the entity and concept lists for the model. Each
open slot holds the marker `TODO(ingest)`, and `validate-wiki.py` fails while
any marker remains.

For a source that changed since ingest, pass `--refresh`. The script then
updates `source_hash` and `date_ingested` on the existing page and touches
nothing else.

Usage:
    scaffold-source.py [--vault DIR] [--slug SLUG] [--refresh] RAW_PATH

RAW_PATH is relative to the vault root, or absolute.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402

TODO = wl.PLACEHOLDER


def clean_name(value) -> str:
    """Turn a frontmatter author value into plain text without wikilink brackets."""
    items = value if isinstance(value, list) else [value]
    names = [re.sub(r"\[\[([^\]]+)\]\]", lambda m: wl.wikilink_target(m.group(1)), str(v)).strip() for v in items if v]
    return ", ".join(n for n in names if n)


def unique_slug(vault: Path, base: str) -> str:
    taken = {p.path.stem for p in wl.pages(vault, "sources")}
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def build_page(rel: str, raw_fm: dict, digest: str, title: str, date: str) -> str:
    published = raw_fm.get("published") or raw_fm.get("date_added")
    inline = "[source_type::article]" + (f" [original_date::{published}]" if published else "")
    return f"""---
type: source-summary
title: {wl.quote(title)}
source_path: {wl.quote(rel)}
source_hash: {wl.quote(digest)}
source_url: {wl.quote(str(raw_fm.get("source") or raw_fm.get("url") or ""))}
author: {wl.quote(clean_name(raw_fm.get("author")))}
date_ingested: {date}
tags:
  - wiki/source
---

# {title}

{inline}

## Summary

{TODO} Two or three factual paragraphs. No interpretation.

## Key Claims

- {TODO} One claim per bullet, close to the source's own words.

## Entities Mentioned

- {TODO} [[Entity name]] - one line on its role in this source

## Concepts Touched

- {TODO} [[Concept name]] - one line on how this source bears on it

## Raw Source

[[{rel.removesuffix(".md")}|Original note]]
"""


def refresh(page: wl.Page, vault: Path, digest: str) -> int:
    text = wl.set_frontmatter_value(page.text, "source_hash", wl.quote(digest))
    text = wl.set_frontmatter_value(text, "date_ingested", wl.today())
    page.path.write_text(text, encoding="utf-8")
    print(f"refreshed {page.path.relative_to(vault).as_posix()}  {digest}")
    return 0


def create(vault: Path, rel: str, digest: str, slug: str | None) -> int:
    raw_fm = wl.parse_frontmatter(vault / rel)
    title = str(raw_fm.get("title") or Path(rel).stem)
    slug = slug or unique_slug(vault, wl.slugify(title))
    target = wl.source_page_path(vault, slug)
    if target.exists():
        print(f"error: {target.name} exists; pick another --slug", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_page(rel, raw_fm, digest, title, wl.today()), encoding="utf-8")
    print(f"created {target.relative_to(vault).as_posix()}  slug={slug}  sha256={digest}")
    return 0


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("raw", help="raw source path, relative to the vault root or absolute")
    parser.add_argument("--slug", help="page name; default is derived from the title")
    parser.add_argument("--refresh", action="store_true", help="re-stamp hash and date on an existing page")
    args, vault = wl.parse(parser)

    raw_abs = Path(args.raw)
    raw_abs = raw_abs if raw_abs.is_absolute() else vault / raw_abs
    try:
        rel = raw_abs.resolve().relative_to(vault).as_posix()
    except ValueError:
        print(f"error: {raw_abs} is outside the vault", file=sys.stderr)
        return 2
    if not (wl.is_source_path(rel) and (vault / rel).is_file()):
        print(f"error: {rel} is not a raw source (see check-sources.py)", file=sys.stderr)
        return 2

    existing = wl.source_pages(vault).get(rel)
    if args.refresh:
        if existing is None:
            print(f"error: no source page names {rel}; run without --refresh", file=sys.stderr)
            return 2
        return refresh(existing, vault, wl.sha256_file(vault / rel))
    if existing is not None:
        print(f"error: {existing.path.name} already covers {rel}; use --refresh", file=sys.stderr)
        return 2
    return create(vault, rel, wl.sha256_file(vault / rel), args.slug)


if __name__ == "__main__":
    raise SystemExit(main())
