#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Append the ingest entry for one source to `Wiki/log.md`.

The script reads the source page and finds the entity and concept pages that
link to it. A page whose `date_created` is today counts as created. Any other
linking page counts as updated. The entry follows one fixed format:

    ## [YYYY-MM-DD] ingest | <Source Title>

    - Source: [[<raw path without .md>]]
    - Created: [[<slug>]] (source)
    - Created entities: ...
    - Updated entities: ...
    - Created concepts: ...
    - Updated concepts: ...
    - Note: ...

Empty lines are left out. A source that already has an entry is skipped with
exit code 0, so a rerun is safe. Pass `--note` for anything the model must say
that the page lists cannot: a contradiction, a skipped entity, a vendor caveat.

Usage:
    log-entry.py [--vault DIR] [--date YYYY-MM-DD] [--note TEXT]... [--dry-run] SLUG
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("slug", help="name of the source page, without .md")
    parser.add_argument("--date", default=wl.today(), help="entry date (default: today)")
    parser.add_argument("--note", action="append", default=[], help="a free-text line; repeat for more")
    parser.add_argument("--dry-run", action="store_true", help="print the entry instead of appending it")
    args, vault = wl.parse(parser)

    slug = wl.resolve_slug(vault, args.slug)
    if args.dry_run:
        print(ops.build_log_entry(vault, slug, args.date, args.note))
    elif ops.append_log_entry(vault, slug, args.date, args.note):
        print(f"appended log entry for {slug}")
    else:
        print(f"log.md already has an entry for {slug}; nothing added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
