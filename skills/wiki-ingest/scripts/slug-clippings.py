#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Rename clippings with a space in the file name to slug file names.

Run it once on an old vault. New clippings get a slug name at ingest, so this
script is the backfill for clippings that were ingested earlier.

For every raw file in `Clippings/` whose name is not a slug, the script:

- renames it to `page_slug(<file stem>).md` with `git mv`;
- sets `source_path` on each source page that names it;
- rewrites every wikilink in `Wiki/`, `Ideas/` and `Inbox/` that targets the old
  name to `[[Clippings/slug|Old name]]`. A link keeps its display text and its
  `#heading` or `^block` suffix. An embed keeps its own form. Links in code
  stay as they are.

Then it rebuilds the `Wiki/index.md` tables and appends an entry to
`Wiki/log.md`.

The script never edits the content of a clipping, and it never writes
`Twitter-Captures/`. It checks that each clipping has the same SHA-256 after the
move, so every `source_hash` still matches. If one hash changes, it moves every
file back and exits 1. A link to an old name in a file outside `Wiki/`,
`Ideas/` and `Inbox/` stays as it is. The report lists those links.

The script refuses to run on a collision: two clippings give one name, or a note
in the same folder already has the name. It lists each collision and exits 1. A
clash is only a warning: a note in another folder has the same name, so a link
without a folder path is ambiguous in Obsidian.

`--dry-run` writes nothing. It prints the rename map, the source pages it would
change, the link count per file, every clash and every collision.

To choose another name, pass `--clip-slug "Old file name=new-slug"` once per
clipping. The slug must be lowercase letters, digits and hyphens.

Usage:
    slug-clippings.py [--vault DIR] [--dry-run] [--clip-slug "OLD NAME=NEW-SLUG"]...

Exit code: 0 on success or a clean dry run, 1 on a collision or a hash change,
2 for a usage error.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikiclips as clips  # noqa: E402
import _wikilib as wl  # noqa: E402
import _wikimigrate as mig  # noqa: E402
import _wikiops as ops  # noqa: E402


def print_plan(vault: Path, plan: clips.Plan) -> None:
    print(f"Rename map ({len(plan.renames)} clipping(s)):")
    for r in plan.renames:
        print(f"  {clips.rel(vault, r.old)} -> {clips.rel(vault, r.new)}")
    print(f"\nSource pages to change ({len(plan.pages)}):")
    for page, (old, new) in sorted(plan.pages.items()):
        print(f"  {page}: source_path {old} -> {new}")
    links = sum(p.links for p in plan.files)
    print(f"\nLink rewrites ({links} link(s) in {sum(1 for p in plan.files if p.links)} file(s)):")
    for p in plan.files:
        if p.links:
            print(f"  {clips.rel(vault, p.path)}: {p.links}")
    if plan.stale:
        print(f"\nSource pages whose source_hash already differs from the clipping ({len(plan.stale)}):")
        for page in plan.stale:
            print(f"  {page}")
    if plan.outside:
        print(
            f"\nLinks the script does not edit ({sum(plan.outside.values())} link(s) in {len(plan.outside)} file(s)):"
        )
        for rel, count in sorted(plan.outside.items()):
            print(f"  {rel}: {count}")
    if plan.unreadable:
        print(f"\nSkipped, not valid UTF-8 ({len(plan.unreadable)}):")
        for rel in plan.unreadable:
            print(f"  {rel}")
    print(f"\nName clashes with notes in other folders ({len(plan.clashes)}):")
    for slug, group in sorted(plan.clashes.items()):
        print(f"  {slug}")
        for rel in group:
            print(f"    - {rel}")
    if not plan.clashes:
        print("  none")


def print_collisions(collisions: dict[str, list[str]]) -> None:
    print(f"{len(collisions)} collision(s). Pass --clip-slug to settle them, then run again:")
    for key, group in sorted(collisions.items()):
        print(f"  {key}")
        for rel in group:
            print(f"    - {rel}")


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument(
        "--clip-slug", action="append", default=[], metavar="OLD=NEW", help="use NEW as the name for the clipping OLD"
    )
    args, vault = wl.parse(parser)

    overrides = {}
    for item in args.clip_slug:
        old, _, new = item.partition("=")
        if not old.strip() or not clips.valid_slug(new):
            parser.error(f"--clip-slug {item!r}: use OLD NAME=lowercase-slug")
        overrides[old.strip()] = new
    plan = clips.plan_backfill(vault, overrides)
    if args.dry_run or plan.collisions:
        print_plan(vault, plan)
    if plan.collisions:
        print()
        print_collisions(plan.collisions)
        return 1
    if args.dry_run:
        print("\nNo collisions. Dry run: nothing written.")
        return 0
    if not plan.renames:
        print("No clipping needs a slug file name. Nothing to do.")
        return 0

    try:
        clips.apply_backfill(vault, plan)
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    links = sum(p.links for p in plan.files)
    mig.append_log(vault, clips.log_entry(wl.today(), len(plan.renames), links, len(plan.pages)))
    ops.write_index(vault)
    print(
        f"Renamed {len(plan.renames)} clipping(s). Set source_path on {len(plan.pages)} page(s). Rewrote {links} link(s)."
    )
    if plan.outside:
        print(
            f"{sum(plan.outside.values())} link(s) in {len(plan.outside)} file(s) outside the scope still use the old names."
        )
    print("Next: run validate-wiki.py, then commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
