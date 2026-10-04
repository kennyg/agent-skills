#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Rename wiki pages with spaces in their file names to slug file names.

For every `Wiki/` page whose file name has a space, the script:

- renames it to the lowercase kebab-case slug of its title, with `git mv`;
- adds `title` and `aliases` to the frontmatter where they are missing, and
  lists the old file name in `aliases`;
- rewrites every wikilink in `Wiki/`, `Ideas/` and `Inbox/` that targets the page
  to `[[slug|Title]]`. A link keeps its display text and its `#heading` or
  `^block` suffix. An embed keeps its own form. Links in code are left alone.

Then it regenerates the `Wiki/index.md` tables and appends an entry to
`Wiki/log.md`.

The script never writes outside `Wiki/`, `Ideas/` and `Inbox/`. A link to a
renamed page in `Clippings/`, `Twitter-Captures/` or another folder stays as it
is and no longer opens in Obsidian. The report lists those links. Obsidian does
not resolve a link through `aliases`.

The script refuses to run when two titles give one slug, or when a slug matches
an existing note name. It lists each collision and exits 1. Fix the titles
first.

`--dry-run` writes nothing. It prints the rename map, the link count per file,
the links it cannot rewrite and any collision.

To settle a collision, pass `--slug "Old file name=new-slug"` once per page. The
slug must be lowercase letters, digits and hyphens. The title stays as it is.

Usage:
    migrate-slugs.py [--vault DIR] [--dry-run] [--slug "OLD NAME=NEW-SLUG"]...

Exit code: 0 on success or a clean dry run, 1 on a collision, 2 for a usage error.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402
import _wikimigrate as mig  # noqa: E402
import _wikiops as ops  # noqa: E402


def print_collisions(collisions: dict[str, list[str]]) -> None:
    print(f"{len(collisions)} collision(s). Fix the titles, then run again:")
    for key, group in sorted(collisions.items()):
        print(f"  {key}")
        for rel in group:
            print(f"    - {rel}")


def print_plan(vault: Path, renames, plans, outside, unreadable) -> None:
    print(f"Rename map ({len(renames)} page(s)):")
    for r in renames:
        print(f"  {r.old.relative_to(vault).as_posix()} -> {r.new.relative_to(vault).as_posix()}")
    total = sum(p.links for p in plans)
    print(f"\nLink rewrites ({total} link(s) in {sum(1 for p in plans if p.links)} file(s)):")
    for p in plans:
        if p.links:
            print(f"  {p.path.relative_to(vault).as_posix()}: {p.links}")
    if outside:
        print(f"\nLinks the script does not edit ({sum(outside.values())} link(s) in {len(outside)} file(s)):")
        for rel, count in sorted(outside.items()):
            print(f"  {rel}: {count}")
    if unreadable:
        print(f"\nSkipped, not valid UTF-8 ({len(unreadable)}):")
        for rel in unreadable:
            print(f"  {rel}")


def main() -> int:
    parser = wl.make_parser(__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument(
        "--slug", action="append", default=[], metavar="OLD=NEW", help="use NEW as the slug for the page named OLD"
    )
    args, vault = wl.parse(parser)

    overrides = {}
    for item in args.slug:
        old, _, new = item.partition("=")
        if not old.strip() or wl.slugify(new, limit=None, fallback="") != new:
            parser.error(f"--slug {item!r}: use OLD NAME=lowercase-slug")
        overrides[old.strip()] = new
    renames, collisions = mig.plan(vault, overrides)
    plans, outside, unreadable = mig.plan_files(vault, renames)
    if args.dry_run or collisions:
        print_plan(vault, renames, plans, outside, unreadable)
    if collisions:
        print()
        print_collisions(collisions)
        return 1
    if args.dry_run:
        print("\nNo collisions. Dry run: nothing written.")
        return 0
    if not renames:
        print("No wiki page has a space in its file name. Nothing to do.")
        return 0

    mig.apply(vault, plans)
    links = sum(p.links for p in plans)
    files = sum(1 for p in plans if p.links)
    mig.append_log(vault, mig.log_entry(wl.today(), len(renames), links, files))
    ops.write_index(vault)
    print(f"Renamed {len(renames)} page(s). Rewrote {links} link(s) in {files} file(s).")
    if outside:
        print(f"{sum(outside.values())} link(s) in {len(outside)} file(s) outside the scope still use the old names.")
    print("Next: run validate-wiki.py, then commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
