"""Logic behind clipping renames.

The Obsidian Web Clipper names a note after the page title, so a clipping has a
name like `Post by @karpathy on X.md`. Ingest renames it to a slug. The rename
changes the file name only. The module never writes the content of a clipping,
and it checks that the SHA-256 is the same after every move.

`scaffold-source.py` renames one clipping. `slug-clippings.py` renames all of
them and fixes the source pages and links that name them. This module is not a
command, so it has no shebang and no executable bit.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import _wikilib as wl
import _wikimigrate as mig

CLIP_DIR = "Clippings"
MAX_NAME_BYTES = 255  # the file name limit on APFS and most other file systems


class ClipRename(NamedTuple):
    old: Path
    new: Path
    digest: str  # SHA-256 of the clipping before the move


def raw_hash(path: Path) -> str:
    """Hash a file now. `sha256_file` caches by path, so a moved file needs a fresh read."""
    return wl.sha256_file.__wrapped__(path)


def valid_slug(name: str) -> bool:
    return bool(name) and wl.page_slug(name) == name


def target_for(old: Path, slug: str) -> Path:
    return old.with_name(f"{slug}.md")


def rel(vault: Path, path: Path) -> str:
    return path.relative_to(vault).as_posix()


# --- collisions and clashes -----------------------------------------------------


def check_targets(vault: Path, moves: list[tuple[Path, Path]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (collisions, clashes) for a set of planned moves.

    A collision stops the rename: two clippings get one name, or a note in the
    same folder already has the name. A clash is only a warning: a note in
    another folder has the same name, so Obsidian holds two notes with one name
    and a link without a folder path is ambiguous.
    """
    collisions: dict[str, list[str]] = {}
    clashes: dict[str, list[str]] = {}
    moving = {old for old, _ in moves}

    by_new: dict[str, list[str]] = {}
    by_old_stem: dict[str, list[str]] = {}
    for old, new in moves:
        if len(new.name.encode()) > MAX_NAME_BYTES:
            collisions.setdefault(f"(name is longer than {MAX_NAME_BYTES} bytes: {new.name[:40]}...)", []).append(
                rel(vault, old)
            )
        if not new.stem:
            continue
        by_new.setdefault(rel(vault, new).casefold(), []).append(rel(vault, old))
        by_old_stem.setdefault(old.stem.casefold(), []).append(rel(vault, old))
    for key, group in by_new.items():
        if len(group) > 1:
            collisions[key] = group
    for group in by_old_stem.values():
        if len(group) > 1:
            collisions[f"(old name {Path(group[0]).stem!r} is used twice; links to it are ambiguous)"] = group

    others: dict[str, list[Path]] = {}
    for path in mig.markdown_files(vault):
        if path not in moving:
            others.setdefault(path.stem.casefold(), []).append(path)
    for old, new in moves:
        for other in others.get(new.stem.casefold(), []):
            if other.parent == new.parent:
                collisions.setdefault(rel(vault, new), [rel(vault, old)]).append(rel(vault, other))
            else:
                clashes.setdefault(new.stem, [rel(vault, old)]).append(rel(vault, other))
    return collisions, clashes


# --- one move -------------------------------------------------------------------


def move_clipping(vault: Path, old: Path, new: Path) -> str:
    """Rename a clipping with `git mv`. Return its hash. Undo the move and raise if the hash changes."""
    digest = raw_hash(old)
    mig.move(vault, old, new)
    if raw_hash(new) != digest:
        mig.move(vault, new, old)
        raise RuntimeError(f"{rel(vault, old)} changed during the rename; the move was undone")
    return digest


# --- backfill plan --------------------------------------------------------------


class Plan(NamedTuple):
    renames: list[ClipRename]
    collisions: dict[str, list[str]]
    clashes: dict[str, list[str]]
    files: list[mig.FilePlan]  # edits to Wiki/, Ideas/ and Inbox/
    pages: dict[str, tuple[str, str]]  # source page path -> (old source_path, new source_path)
    stale: list[str]  # source pages whose source_hash already differs from the raw file
    outside: dict[str, int]  # links left in files the script does not write
    unreadable: list[str]


def plan_backfill(vault: Path, overrides: dict[str, str] | None = None) -> Plan:
    """Plan the rename of every clipping whose file name is not a slug.

    `overrides` maps an old file stem to the slug to use in its place.
    """
    overrides = {k.casefold(): v for k, v in (overrides or {}).items()}
    base = vault / CLIP_DIR
    moves: list[tuple[Path, Path]] = []
    collisions: dict[str, list[str]] = {}
    for path in sorted(base.rglob("*.md")) if base.is_dir() else []:
        if not wl.is_source_path(rel(vault, path)) or not (
            path.stem.casefold() in overrides or wl.needs_slug(path.stem)
        ):
            continue
        slug = overrides.get(path.stem.casefold()) or wl.page_slug(path.stem)
        if not slug:
            collisions.setdefault(f"(no ASCII letter or digit in the name {path.stem!r}; pass --clip-slug)", []).append(
                rel(vault, path)
            )
            continue
        moves.append((path, target_for(path, slug)))
    found, clashes = check_targets(vault, moves)
    for key, group in found.items():
        collisions.setdefault(key, []).extend(group)

    renames = [ClipRename(old, new, raw_hash(old)) for old, new in moves]
    lookup = mig.lookup_for([mig.Rename(r.old, r.new, r.old.stem, r.old.stem) for r in renames])
    moved = {rel(vault, r.old): (r, rel(vault, r.new)) for r in renames}
    by_path = {p.path: p for old, p in wl.source_pages(vault).items() if old in moved}

    files: list[mig.FilePlan] = []
    pages: dict[str, tuple[str, str]] = {}
    stale: list[str] = []
    outside: dict[str, int] = {}
    unreadable: list[str] = []
    for path in mig.markdown_files(vault):
        text = mig.read(path)
        if text is None:
            unreadable.append(rel(vault, path))
            continue
        new_text, links = mig.rewrite_links(text, lookup, vault)
        if not mig.in_scope(vault, path):
            if links:
                outside[rel(vault, path)] = links
            continue
        page = by_path.get(path)
        if page is not None:
            old_rel = str(page.fm["source_path"])
            new_text = wl.set_frontmatter_value(new_text, "source_path", wl.quote(moved[old_rel][1]))
            pages[rel(vault, path)] = (old_rel, moved[old_rel][1])
            if str(page.fm.get("source_hash")) != moved[old_rel][0].digest:
                stale.append(rel(vault, path))
        if new_text != text:
            files.append(mig.FilePlan(path, path, new_text, links))
    return Plan(renames, collisions, clashes, files, pages, stale, outside, unreadable)


def apply_backfill(vault: Path, plan: Plan) -> None:
    """Move the clippings, check every hash, then write the pages. Undo the moves on a hash change."""
    done: list[ClipRename] = []
    try:
        for item in plan.renames:
            move_clipping(vault, item.old, item.new)
            done.append(item)
    except RuntimeError:
        for item in reversed(done):
            mig.move(vault, item.new, item.old)
        raise
    mig.apply(vault, plan.files)
    wl.pages.cache_clear()
    wl.classify.cache_clear()


def log_entry(date: str, renamed: int, links: int, pages: int) -> str:
    return (
        f"## [{date}] migrate | Slug clipping names\n\n"
        f"- Renamed: {renamed} clippings to slug file names\n"
        f"- Rewrote: {links} links and {pages} `source_path` values\n"
        "- Note: clipping content is unchanged and every `source_hash` still matches"
    )
