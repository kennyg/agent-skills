#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Run all bookkeeping for one ingested source, then validate.

Order of steps:
0. validate the pages and reject unfinished ones before any write;
1. regenerate the `Wiki/index.md` tables (`rebuild-index.py`);
2. refresh the counts in `Wiki/overview.md` (`update-overview.py`);
3. append the ingest entry to `Wiki/log.md` (`log-entry.py`);
4. refresh the search index, or skip if `qmd` is absent (`qmd-refresh.py`);
5. validate the whole ingest (`validate-wiki.py`).

The steps run in one process, so the pages and hashes are read once. The script
stops at the first failing step. Run it after the source page, entity pages and
concept pages are written. A rerun is safe: the log step is skipped when the
entry exists.

Usage:
    finalize-ingest.py [--vault DIR] [--note TEXT]... SLUG_OR_RAW_PATH
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikiops as ops  # noqa: E402


def show(report: ops.Report, checked: int) -> bool:
    for line in report.errors:
        print(f"error:   {line}")
    for line in report.warnings:
        print(f"warning: {line}")
    print(f"{checked} page(s) checked: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return not report.errors


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("source", help="source page name or raw path")
    parser.add_argument("--note", action="append", default=[], help="free-text line for the log entry")
    args, vault = wl.parse(parser)
    slug = wl.resolve_slug(vault, args.source)

    print("== validate pages")
    if not show(*ops.validate(vault, slug, pages_only=True)):
        print("stopped: fix the pages above, then rerun", file=sys.stderr)
        return 1
    print(f"== index: {'rebuilt' if ops.write_index(vault) else 'unchanged'}")
    changed, unmatched = ops.write_overview(vault)
    for pattern in unmatched:
        print(f"error: no line in overview.md matches {pattern}", file=sys.stderr)
    print(f"== overview: {'updated' if changed else 'unchanged'}")
    added = ops.append_log_entry(vault, slug, wl.today(), args.note)
    print(f"== log: {'entry appended' if added else 'entry exists, skipped'}")
    print("== qmd")
    code = ops.refresh_qmd()
    if code != 0:
        return code
    print("== validate ingest")
    if not show(*ops.validate(vault, slug)):
        print("stopped: validate-wiki.py found errors", file=sys.stderr)
        return 1
    print(f"ingest of [[{slug}]] is complete and valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
