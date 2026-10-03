#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Check that the wiki is consistent. An ingest is done only when this passes.

Checks:
- schema: each page has the frontmatter keys and `wiki/*` tag for its type;
- links: every `[[wikilink]]` in `Wiki/` resolves to a page or a raw source;
- hashes: each `source_hash` equals the SHA-256 of its raw file;
- placeholders: no `TODO(ingest)` marker remains;
- index: `Wiki/index.md` equals what `rebuild-index.py` would write;
- overview: the counts in `Wiki/overview.md` are current;
- log: each source page has an ingest entry in `Wiki/log.md`.

A missing log entry is a warning for the whole wiki, because older sources
predate the fixed format. It is an error for the source named by `--source`.

With `--source`, the page checks cover that source page and the entity and
concept pages that link to it. The index and overview checks stay global. The
source must also be out of the `check-sources.py` queue.

`--pages-only` runs the schema, link, hash and placeholder checks and skips the
rest. `finalize-ingest.py` uses it to reject unfinished pages before it writes
the index, overview and log.

Exit code: 0 when there are no errors, 1 otherwise, 2 for a usage error.

Usage:
    validate-wiki.py [--vault DIR] [--source SLUG_OR_RAW_PATH] [--pages-only] [--strict]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--source", help="check one ingest: a source page name or a raw path")
    parser.add_argument("--pages-only", action="store_true", help="skip the index, overview, log and queue checks")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args, vault = wl.parse(parser)

    slug = wl.resolve_slug(vault, args.source) if args.source else None
    report, checked = ops.validate(vault, slug, args.pages_only)
    for line in report.errors:
        print(f"error:   {line}")
    for line in report.warnings:
        print(f"warning: {line}")
    print(f"{checked} page(s) checked: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors or (args.strict and report.warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
