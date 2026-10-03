#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
idea.py — mechanical steps for the idea-capture skill.

Three subcommands. The agent writes the words. This script does the parts that
must come out the same every time: the slug, the duplicate lookup, the
frontmatter, the task line and the Base install.

    idea.py find "<title or phrase>"
    idea.py new  --title T --idea S --why W [--question Q ...] [--source S]
                 [--tag T ...] [--related NAME ...] [--no-task]
    idea.py install-base

The vault root is --vault, else $CLAUDE_PROJECT_DIR, else the current directory.
The script never writes outside Ideas/ and Inbox/Tasks.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from pathlib import Path

STATUSES = ("captured", "exploring", "parked", "done")
SKILL_DIR = Path(__file__).resolve().parent.parent
BASE_ASSET = SKILL_DIR / "assets" / "ideas.base"
STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or the to with".split()
)
# Share of the query tokens a candidate must hold to count as a close match.
CLOSE_MATCH = 0.5


def slugify(text: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:60].rstrip("-") or "idea"


def tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS}


def vault_root(arg: str | None) -> Path:
    root = Path(arg or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    if not root.is_dir():
        sys.exit(f"idea.py: vault root is not a directory: {root}")
    return root


def candidates(root: Path):
    """Yield (kind, path) for every note that can hold a duplicate."""
    for kind, folder in (("idea", "Ideas"), ("concept", "Wiki/concepts")):
        base = root / folder
        if base.is_dir():
            for path in sorted(base.glob("*.md")):
                yield kind, path


def find_matches(root: Path, query: str) -> list[tuple[str, Path, float]]:
    wanted = tokens(query)
    slug = slugify(query)
    found = []
    for kind, path in candidates(root):
        if slugify(path.stem) == slug:
            found.append((kind, path, 1.0))
            continue
        have = tokens(path.stem)
        if wanted and have:
            score = len(wanted & have) / len(wanted)
            if score >= CLOSE_MATCH:
                found.append((kind, path, score))
    return sorted(found, key=lambda m: -m[2])


def cmd_find(args: argparse.Namespace) -> int:
    root = vault_root(args.vault)
    matches = find_matches(root, args.query)
    print(f"slug: {slugify(args.query)}")
    if not matches:
        print("matches: none")
        return 0
    for kind, path, score in matches:
        print(f"{kind}\t{score:.2f}\t{path.relative_to(root)}")
    return 0


def yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_note(args: argparse.Namespace, today: str) -> str:
    tags = ["idea"] + [t for t in args.tag if t != "idea"]
    lines = ["---", "type: idea", "status: captured", f"date_captured: {today}", "tags:"]
    lines += [f"  - {t}" for t in tags]
    if args.source:
        lines.append(f"source: {yaml_str(args.source)}")
    lines += ["---", "", args.idea.strip(), "", "## Why it matters", "", args.why.strip(), ""]
    lines += ["## Open questions", ""]
    lines += [f"- {q.strip()}" for q in args.question] or ["- "]
    if args.related:
        lines += ["", "## Related", ""]
        lines += [f"- [[{name}]]" for name in args.related]
    return "\n".join(lines) + "\n"


def install_base(root: Path) -> str:
    target = root / "Ideas" / "Ideas.base"
    if target.exists():
        return f"kept {target.relative_to(root)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(BASE_ASSET.read_text(encoding="utf-8"), encoding="utf-8")
    return f"installed {target.relative_to(root)}"


def cmd_install_base(args: argparse.Namespace) -> int:
    print(install_base(vault_root(args.vault)))
    return 0


def append_task(root: Path, slug: str, title: str, today: str) -> str:
    tasks = root / "Inbox" / "Tasks.md"
    line = f"- [ ] Explore idea [[{slug}|{title}]] #idea ➕ {today}\n"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    existing = tasks.read_text(encoding="utf-8") if tasks.exists() else ""
    if f"[[{slug}|" in existing or f"[[{slug}]]" in existing:
        return "kept Inbox/Tasks.md (task already present)"
    if existing and not existing.endswith("\n"):
        line = "\n" + line
    with tasks.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return "appended Inbox/Tasks.md"


def cmd_new(args: argparse.Namespace) -> int:
    root = vault_root(args.vault)
    slug = slugify(args.title)
    note = root / "Ideas" / f"{slug}.md"
    if note.exists():
        sys.exit(
            f"idea.py: Ideas/{slug}.md exists. Update it instead of creating a duplicate."
        )
    today = dt.date.today().isoformat()
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(render_note(args, today), encoding="utf-8")
    print(f"created Ideas/{slug}.md")
    print(install_base(root))
    print("skipped Inbox/Tasks.md" if args.no_task else append_task(root, slug, args.title, today))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vault", help="vault root (default: $CLAUDE_PROJECT_DIR or cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find", help="list close matches in Ideas/ and Wiki/concepts/")
    find.add_argument("query")
    find.set_defaults(func=cmd_find)

    new = sub.add_parser("new", help="write an idea note and its backlog line")
    new.add_argument("--title", required=True)
    new.add_argument("--idea", required=True, help="one-sentence statement")
    new.add_argument("--why", required=True, help="why it matters")
    new.add_argument("--question", action="append", default=[], help="open question")
    new.add_argument("--source", help="URL or [[wikilink]]")
    new.add_argument("--tag", action="append", default=[])
    new.add_argument("--related", action="append", default=[], help="note name to link")
    new.add_argument("--no-task", action="store_true", help="skip the Inbox/Tasks.md line")
    new.set_defaults(func=cmd_new)

    base = sub.add_parser("install-base", help="install Ideas/Ideas.base if missing")
    base.set_defaults(func=cmd_install_base)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
