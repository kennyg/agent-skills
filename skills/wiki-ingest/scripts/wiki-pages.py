#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""List, find, create and bump entity and concept pages.

Commands:
    list [entities|concepts] [--json]
        Print every page with its kind or confidence, `source_count` and aliases.
    find NAME... [--json]
        Resolve each name against page names, titles and `aliases`. The match
        ignores case and punctuation. Print `exists` or `new` for each name.
    new entity|concept NAME --source SLUG [--kind KIND] [--confidence LEVEL] [--alias A]...
        Create a page with correct frontmatter and `source_count: 1`.
    bump NAME --source SLUG --mention TEXT
        Add 1 to `source_count`, set `date_updated` to today, and append the
        bullet `- [[SLUG]] - TEXT` to the page's Mentions (entity) or Sources
        (concept) list. The command skips a page that already links the
        source, so a rerun does not count twice.

Usage:
    wiki-pages.py [--vault DIR] COMMAND ...
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wikilib as wl  # noqa: E402

FOLDERS = ("entities", "concepts")
ENTITY_KINDS = ("person", "tool", "org", "repo", "standard")
CONFIDENCE = ("high", "medium", "low")

# What differs between the two page types.
SPEC = {
    "entity": {
        "folder": "entities",
        "list_heading": "Mentions",
        "sections": "## Mentions\n\n- [[{slug}]] - {todo} what this source says about it\n\n## Related\n\n- {todo} [[Related page]]\n",
        "intro": "{todo} One or two factual sentences.\n\n",
    },
    "concept": {
        "folder": "concepts",
        "list_heading": "Sources",
        "sections": (
            "## Key Insights\n\n- {todo} Insight (from [[{slug}]])\n\n## Sources\n\n"
            "- [[{slug}]] - {todo} what it adds\n\n## Related Concepts\n\n- {todo} [[Related page]]\n"
        ),
        "intro": "## Definition\n\n{todo} What the concept is.\n\n",
    },
}


def as_list(value) -> list[str]:
    if value in (None, ""):
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def inventory(vault: Path, folders: tuple[str, ...] = FOLDERS) -> list[dict]:
    rows = []
    for folder in folders:
        for page in wl.pages(vault, folder):
            rows.append(
                {
                    "name": page.path.stem,
                    "type": wl.FOLDER_TYPE[folder],
                    "kind": wl.first(page.fm, "entity_kind", "confidence") or "",
                    "source_count": page.fm.get("source_count") or 0,
                    "aliases": as_list(page.fm.get("aliases")),
                    "title": str(page.fm.get("title") or page.path.stem),
                    "path": page.path,
                }
            )
    return rows


def lookup(rows: list[dict]) -> dict[str, dict]:
    keys: dict[str, dict] = {}
    for row in rows:
        for label in [row["name"], row["title"], *row["aliases"]]:
            keys.setdefault(wl.normalize(label), row)
    return keys


def cmd_list(vault: Path, args) -> int:
    rows = inventory(vault, FOLDERS if args.group == "all" else (args.group,))
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    for row in rows:
        aliases = f"  aliases: {', '.join(row['aliases'])}" if row["aliases"] else ""
        print(f"{row['type']:8} {row['name']}  [{row['kind']}]  sources={row['source_count']}{aliases}")
    return 0


def cmd_find(vault: Path, args) -> int:
    keys = lookup(inventory(vault))
    results = []
    for name in args.names:
        row = keys.get(wl.normalize(name))
        results.append(
            {
                "query": name,
                "status": "exists" if row else "new",
                "page": row["name"] if row else None,
                "type": row["type"] if row else None,
            }
        )
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    for item in results:
        if item["status"] == "exists":
            print(f"exists  {item['query']}  ->  [[{item['page']}]] ({item['type']})")
        else:
            print(f"new     {item['query']}")
    return 0


def cmd_new(vault: Path, args) -> int:
    spec = SPEC[args.type]
    existing = lookup(inventory(vault)).get(wl.normalize(args.name))
    target = vault / "Wiki" / spec["folder"] / f"{args.name}.md"
    if existing or target.exists():
        print(f"error: [[{existing['name'] if existing else args.name}]] already exists; use `bump`", file=sys.stderr)
        return 2
    if not wl.source_page_path(vault, args.source).is_file():
        print(f"error: no source page {args.source}", file=sys.stderr)
        return 2
    if args.type == "entity":
        if args.kind not in ENTITY_KINDS:
            print("error: entities need --kind (" + "/".join(ENTITY_KINDS) + ")", file=sys.stderr)
            return 2
        extra = f"entity_kind: {args.kind}\n"
        order = ("title", "extra", "dates", "count")
    else:
        if args.confidence not in CONFIDENCE:
            print("error: concepts need --confidence (" + "/".join(CONFIDENCE) + ")", file=sys.stderr)
            return 2
        extra = f"confidence: {args.confidence}\n"
        order = ("title", "dates", "count", "extra")
    date = wl.today()
    parts = {
        "title": f"title: {wl.quote(args.name)}\n",
        "extra": extra,
        "dates": f"date_created: {date}\ndate_updated: {date}\n",
        "count": "source_count: 1\n",
    }
    aliases = "aliases:\n" + "".join(f"  - {wl.quote(a)}\n" for a in args.alias) if args.alias else ""
    head = (
        f"---\ntype: {args.type}\n{''.join(parts[k] for k in order)}{aliases}tags:\n  - {wl.TYPE_TAG[args.type]}\n---\n"
    )
    fields = {"slug": args.source, "todo": wl.PLACEHOLDER}
    body = f"\n# {args.name}\n\n{spec['intro'].format(**fields)}{spec['sections'].format(**fields)}"
    target.write_text(head + body, encoding="utf-8")
    print(f"created {target.relative_to(vault).as_posix()}")
    return 0


def add_bullet(text: str, heading: str, bullet: str) -> str:
    """Append a bullet to the end of a `## heading` section, or add the section."""
    match = re.search(rf"(?m)^## {heading}[ \t]*$", text)
    if match is None:
        return text.rstrip() + f"\n\n## {heading}\n\n{bullet}\n"
    nxt = re.search(r"(?m)^## ", text[match.end() :])
    end = match.end() + nxt.start() if nxt else len(text)
    section = text[match.end() : end].rstrip("\n")
    tail = "\n\n" if nxt else "\n"
    return text[: match.end()] + section + "\n" + bullet + tail + text[end:]


def cmd_bump(vault: Path, args) -> int:
    row = lookup(inventory(vault)).get(wl.normalize(args.name))
    if row is None:
        print(f"error: no page for {args.name}; use `new`", file=sys.stderr)
        return 2
    text = row["path"].read_text(encoding="utf-8")
    if wl.links_to(text, args.source):
        print(f"skipped [[{row['name']}]]: already links [[{args.source}]]")
        return 0
    count = int(row["source_count"] or 0) + 1
    text = wl.set_frontmatter_value(text, "source_count", str(count))
    text = wl.set_frontmatter_value(text, "date_updated", wl.today(), after="date_created")
    heading = SPEC[row["type"]]["list_heading"]
    row["path"].write_text(add_bullet(text, heading, f"- [[{args.source}]] - {args.mention}"), encoding="utf-8")
    print(f"bumped [[{row['name']}]] source_count {count - 1} -> {count}")
    return 0


def main() -> int:
    parser = wl.make_parser(__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list entity and concept pages")
    p_list.add_argument("group", nargs="?", choices=["all", *FOLDERS], default="all")
    p_list.add_argument("--json", action="store_true")

    p_find = sub.add_parser("find", help="resolve names to existing pages")
    p_find.add_argument("names", nargs="+")
    p_find.add_argument("--json", action="store_true")

    p_new = sub.add_parser("new", help="create an entity or concept page")
    p_new.add_argument("type", choices=list(SPEC))
    p_new.add_argument("name")
    p_new.add_argument("--source", required=True, help="slug of the source page")
    p_new.add_argument("--kind", help="entity kind: " + ", ".join(ENTITY_KINDS))
    p_new.add_argument("--confidence", help="concept confidence: " + ", ".join(CONFIDENCE))
    p_new.add_argument("--alias", action="append", default=[])

    p_bump = sub.add_parser("bump", help="count one more source on an existing page")
    p_bump.add_argument("name")
    p_bump.add_argument("--source", required=True, help="slug of the source page")
    p_bump.add_argument("--mention", required=True, help="one line on what the source says about the page")

    args, vault = wl.parse(parser)
    return {"list": cmd_list, "find": cmd_find, "new": cmd_new, "bump": cmd_bump}[args.command](vault, args)


if __name__ == "__main__":
    raise SystemExit(main())
