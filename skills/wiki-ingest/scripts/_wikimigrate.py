"""Logic behind `migrate-slugs.py`.

The module renames wiki pages with spaces in their file names to slugs and
rewrites the wikilinks that point at them. The functions are pure where they
can be, so the tests call them without a vault. This module is not a command,
so it has no shebang and no executable bit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

import _wikilib as wl

# Folders whose links the migration rewrites. Raw sources are never written.
SCOPE_DIRS = ("Wiki", "Ideas", "Inbox")
SKIP_DIRS = frozenset({".git", ".obsidian", ".trash", "node_modules"})

LINK_RE = re.compile(r"(!?)\[\[([^\]\n]+)\]\]")
ANCHOR_RE = re.compile(r"[#^]")


class Rename(NamedTuple):
    old: Path
    new: Path
    title: str
    old_stem: str


# --- slug and link rewrite ------------------------------------------------------


def code_spans(text: str) -> list[tuple[int, int]]:
    """Return the (start, end) ranges of fenced blocks and inline code spans."""
    return [m.span() for m in wl.FENCED_CODE_RE.finditer(text)] + [m.span() for m in wl.INLINE_CODE_RE.finditer(text)]


def in_table_row(text: str, pos: int) -> bool:
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos].lstrip().startswith("|")


def match_target(target: str, lookup: dict[str, Rename], vault: Path) -> Rename | None:
    """Find the renamed page a link target names, by file name or by vault path."""
    key = target.strip().removesuffix(".md").casefold()
    if "/" not in key:
        return lookup.get(key)
    for rename in lookup.values():
        rel = rename.old.relative_to(vault).as_posix().removesuffix(".md").casefold()
        if rel == key or rel.endswith("/" + key):
            return rename
    return None


def rewrite_links(text: str, lookup: dict[str, Rename], vault: Path) -> tuple[str, int]:
    """Point every link to a renamed page at `[[slug|Title]]`. Return (text, links changed).

    A link keeps its display text, its `#heading` or `^block` suffix, and any
    folder prefix. A link without display text gets the page title. An embed
    keeps its own form, because text after `|` on an embed sets its size.
    Links in code are left alone.
    """
    spans = code_spans(text)
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        if any(start <= m.start() < end for start, end in spans):
            return m.group(0)
        bang, inner = m.groups()
        sep = wl.ALIAS_SEP_RE.search(inner)
        head, display = (inner[: sep.start()], inner[sep.end() :]) if sep else (inner, None)
        anchor = ANCHOR_RE.search(head)
        target, suffix = (head[: anchor.start()], head[anchor.start() :]) if anchor else (head, "")
        rename = match_target(target, lookup, vault)
        if rename is None:
            return m.group(0)
        folder, _, _ = target.strip().rpartition("/")
        new_target = (folder + "/" if folder else "") + rename.new.stem
        if target.strip().endswith(".md"):
            new_target += ".md"
        if sep:
            tail = sep.group(0) + display
        elif bang:
            tail = ""
        else:
            title = re.sub(r"[\[\]|]", "", rename.title).strip()
            tail = ("\\|" if in_table_row(text, m.start()) else "|") + title if title else ""
        count += 1
        return f"{bang}[[{new_target}{suffix}{tail}]]"

    return LINK_RE.sub(repl, text), count


# --- frontmatter ----------------------------------------------------------------


def _insert_line(fm_text: str, line: str, after_key: str | None = None, before_key: str | None = None) -> str:
    lines = fm_text.split("\n")
    at = None
    for index, existing in enumerate(lines):
        if after_key and re.match(rf"{re.escape(after_key)}[ \t]*:", existing):
            at = index + 1
            break
        if before_key and re.match(rf"{re.escape(before_key)}[ \t]*:", existing):
            at = index
            break
    if at is None:
        at = len(lines) - 1 if lines[-1] == "" else len(lines)
        if after_key and not before_key:
            at = 1  # right after the opening delimiter
    lines[at:at] = line.split("\n")
    return "\n".join(lines)


def add_title_and_aliases(text: str, title: str, old_stem: str) -> str:
    """Make sure `title` is set and `aliases` lists the title and the old file name."""
    wanted = list(dict.fromkeys([title, old_stem]))
    split = wl.split_frontmatter(text)
    if split is None:
        items = "".join(f"  - {wl.quote(name)}\n" for name in wanted)
        return f"---\ntitle: {wl.quote(title)}\naliases:\n{items}---\n\n{text}"

    fm_text, body = split
    data = wl.parse_frontmatter_text(text)
    if not data.get("title"):
        fm_text = _insert_line(fm_text, f"title: {wl.quote(title)}", after_key="type")

    raw = data.get("aliases")
    have = [str(a) for a in (raw if isinstance(raw, list) else [raw]) if a]
    missing = [name for name in wanted if name.casefold() not in {a.casefold() for a in have}]
    if not missing:
        return "---" + fm_text + "---" + body

    lines = fm_text.split("\n")
    index = next((i for i, line in enumerate(lines) if re.match(r"aliases[ \t]*:", line)), None)
    if index is None:
        block = "aliases:\n" + "\n".join(f"  - {wl.quote(name)}" for name in missing)
        fm_text = _insert_line(fm_text, block, before_key="tags")
    elif lines[index].split(":", 1)[1].strip():
        # Inline list or scalar: rewrite the line as a block list of everything.
        block = "aliases:\n" + "\n".join(f"  - {wl.quote(name)}" for name in [*have, *missing])
        lines[index : index + 1] = block.split("\n")
        fm_text = "\n".join(lines)
    else:
        end = index + 1
        while end < len(lines) and re.match(r"[ \t]*-([ \t]|$)", lines[end]):
            end += 1
        indent = re.match(r"[ \t]*", lines[index + 1]).group(0) if end > index + 1 else "  "
        lines[end:end] = [f"{indent}- {wl.quote(name)}" for name in missing]
        fm_text = "\n".join(lines)
    return "---" + fm_text + "---" + body


# --- plan -----------------------------------------------------------------------


def markdown_files(vault: Path):
    for root, dirs, files in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(".md"):
                yield Path(root) / name


def read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def plan(vault: Path, overrides: dict[str, str] | None = None) -> tuple[list[Rename], dict[str, list[str]]]:
    """Return (renames, collisions). Collisions map a problem key to the pages in it.

    `overrides` maps an old file stem to the slug to use in its place, to settle a collision.
    """
    overrides = {k.casefold(): v for k, v in (overrides or {}).items()}
    renames: list[Rename] = []
    collisions: dict[str, list[str]] = {}
    for path in sorted((vault / "Wiki").rglob("*.md")):
        if " " not in path.name:
            continue
        text = read(path) or ""
        title = str(wl.parse_frontmatter_text(text).get("title") or path.stem).strip()
        slug = overrides.get(path.stem.casefold()) or wl.page_slug(title)
        rel = path.relative_to(vault).as_posix()
        if not slug:
            collisions.setdefault(f"(no ASCII letter or digit in title {title!r})", []).append(rel)
            continue
        renames.append(Rename(path, path.with_name(f"{slug}.md"), title, path.stem))

    by_slug: dict[str, list[Rename]] = {}
    for rename in renames:
        by_slug.setdefault(rename.new.stem, []).append(rename)
    for slug, group in by_slug.items():
        if len(group) > 1:
            collisions[slug] = [r.old.relative_to(vault).as_posix() for r in group]

    moving = {r.old for r in renames}
    taken: dict[str, list[str]] = {}
    for path in markdown_files(vault):
        if path not in moving:
            taken.setdefault(path.stem.casefold(), []).append(path.relative_to(vault).as_posix())
    for slug, group in by_slug.items():
        if slug in taken:
            found = collisions.setdefault(slug, [r.old.relative_to(vault).as_posix() for r in group])
            found.extend(taken[slug])

    stems: dict[str, list[Rename]] = {}
    for rename in renames:
        stems.setdefault(rename.old_stem.casefold(), []).append(rename)
    for group in stems.values():
        if len(group) > 1:
            name = group[0].old_stem
            collisions.setdefault(f"(old name {name!r} is used twice; links to it are ambiguous)", []).extend(
                r.old.relative_to(vault).as_posix() for r in group
            )
    return renames, collisions


def lookup_for(renames: list[Rename]) -> dict[str, Rename]:
    return {r.old_stem.casefold(): r for r in renames}


class FilePlan(NamedTuple):
    path: Path  # where the file is now
    target: Path  # where it ends up
    text: str  # the new text
    links: int


def in_scope(vault: Path, path: Path) -> bool:
    return path.relative_to(vault).parts[0] in SCOPE_DIRS


def plan_files(vault: Path, renames: list[Rename]) -> tuple[list[FilePlan], dict[str, int], list[str]]:
    """Compute every write. Return (file plans, links left in unedited files by path, unreadable paths)."""
    lookup = lookup_for(renames)
    by_old = {r.old: r for r in renames}
    plans: list[FilePlan] = []
    outside: dict[str, int] = {}
    unreadable: list[str] = []
    for path in markdown_files(vault):
        text = read(path)
        if text is None:
            unreadable.append(path.relative_to(vault).as_posix())
            continue
        new_text, links = rewrite_links(text, lookup, vault)
        if not in_scope(vault, path):
            if links:
                outside[path.relative_to(vault).as_posix()] = links
            continue
        rename = by_old.get(path)
        if rename is not None:
            new_text = add_title_and_aliases(new_text, rename.title, rename.old_stem)
        if new_text != text or rename is not None:
            plans.append(FilePlan(path, rename.new if rename else path, new_text, links))
    return plans, outside, unreadable


# --- apply ----------------------------------------------------------------------


def move(vault: Path, old: Path, new: Path) -> None:
    """Rename with `git mv`, or a plain rename when git does not track the file."""
    done = wl.git(vault, "mv", old.relative_to(vault).as_posix(), new.relative_to(vault).as_posix())
    if done.returncode != 0:
        old.rename(new)


def apply(vault: Path, plans: list[FilePlan]) -> None:
    for item in plans:
        if item.target != item.path:
            move(vault, item.path, item.target)
        item.target.write_bytes(item.text.encode("utf-8"))


def log_entry(date: str, renamed: int, links: int, files: int) -> str:
    return (
        f"## [{date}] migrate | Slug file names\n\n"
        f"- Renamed: {renamed} pages to lowercase slug file names\n"
        f"- Rewrote: {links} links in {files} files to `[[slug|Title]]`\n"
        "- Note: each page keeps its title in `title` and `aliases`"
    )


def append_log(vault: Path, entry: str) -> bool:
    log = vault / "Wiki" / "log.md"
    text = read(log)
    if text is None:
        return False
    log.write_bytes((text.rstrip("\n") + "\n\n" + entry + "\n").encode("utf-8"))
    return True
