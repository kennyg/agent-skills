#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
rebuild-index.py — regenerate Wiki/index.md tables from page frontmatter.

Hand-maintaining index.md works at 25 clippings and stops working at repo
scale: it becomes a single file rewritten on every ingest, and it drifts
silently because nothing checks it. This scans the frontmatter that already
exists on every page and regenerates the tables deterministically.

Prose outside the marker fences is preserved, so the file stays yours:

    <!-- BEGIN:sources -->   ... generated ...   <!-- END:sources -->
    <!-- BEGIN:entities -->  ... generated ...   <!-- END:entities -->
    <!-- BEGIN:concepts -->  ... generated ...   <!-- END:concepts -->
    <!-- BEGIN:synthesis --> ... generated ...   <!-- END:synthesis -->
    <!-- BEGIN:unprocessed --> ... generated --> <!-- END:unprocessed -->

Missing fences are appended under their own heading on first run.

Usage:
    uv run rebuild-index.py <vault-dir>
    uv run check-sources.py <vault> --mode code --json > /tmp/s.json
    uv run rebuild-index.py <vault> --unprocessed /tmp/s.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SECTIONS = ["sources", "entities", "concepts", "synthesis", "unprocessed"]
HEADINGS = {
    "sources": "## Sources",
    "entities": "## Entities",
    "concepts": "## Concepts",
    "synthesis": "## Synthesis",
    "unprocessed": "## Unprocessed",
}
# Legacy (pre-fence) heading spellings to absorb in place on first run, so a
# hand-maintained index migrates without duplicating its tables. Trailing
# "(35)" counts and the older "Unprocessed Sources" wording are tolerated.
LEGACY = {
    "sources": r"Sources",
    "entities": r"Entities",
    "concepts": r"Concepts",
    "synthesis": r"Synthesis",
    "unprocessed": r"Unprocessed(?: Sources)?",
}


def first(fm: dict, *keys):
    """Return the first present, non-empty frontmatter value among keys.

    Both wikis feed this script but name a few fields differently (synthesis
    uses `query` here, `question` there; pages carry `date_updated` or only
    `date_created`). Reading through a fallback list keeps one builder correct
    for both rather than blanking a column when the preferred key is absent.
    """
    for key in keys:
        value = fm.get(key)
        if value not in (None, "", []):
            return value
    return None


def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def cell(value) -> str:
    """Render a frontmatter value as a table cell, escaping pipes."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def link(page: Path) -> str:
    return f"[[{page.stem}]]"


def collect(vault: Path, folder: str) -> list[tuple[Path, dict]]:
    directory = vault / "Wiki" / folder
    if not directory.is_dir():
        return []
    out = []
    for page in sorted(directory.glob("*.md")):
        out.append((page, parse_frontmatter(page)))
    return out


def table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None yet._"
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_sources(vault: Path) -> str:
    rows = []
    for page, fm in collect(vault, "sources"):
        rows.append([
            link(page),
            cell(first(fm, "source_kind") or "file"),
            cell(first(fm, "source_path")),
            cell(first(fm, "date_ingested", "date_updated")),
        ])
    return table(["Source", "Kind", "Path", "Ingested"], rows)


def build_entities(vault: Path) -> str:
    rows = []
    for page, fm in collect(vault, "entities"):
        grounded = first(fm, "realized_by") or []
        rows.append([
            link(page),
            cell(first(fm, "entity_kind")),
            cell(first(fm, "source_count") or 0),
            cell(len(grounded) if grounded else ""),
            cell(first(fm, "date_updated", "date_created")),
        ])
    return table(["Entity", "Kind", "Sources", "Symbols", "Updated"], rows)


def build_concepts(vault: Path) -> str:
    rows = []
    for page, fm in collect(vault, "concepts"):
        grounded = first(fm, "realized_by") or []
        rows.append([
            link(page),
            cell(first(fm, "confidence")),
            cell(first(fm, "source_count") or 0),
            cell(len(grounded) if grounded else ""),
            cell(first(fm, "date_updated", "date_created")),
        ])
    return table(["Concept", "Confidence", "Sources", "Symbols", "Updated"], rows)


def build_synthesis(vault: Path) -> str:
    rows = []
    for page, fm in collect(vault, "synthesis"):
        rows.append([
            link(page),
            cell(first(fm, "question", "query", "title")),
            cell(first(fm, "date_updated", "date_ingested", "date_created")),
        ])
    return table(["Page", "Question", "Updated"], rows)


def build_unprocessed(payload: dict | None) -> str:
    if payload is None:
        return "_Run check-sources.py to populate._"
    rows = []
    for item in payload.get("new") or []:
        rows.append([cell(item.get("source")), "new", ""])
    for item in payload.get("changed") or []:
        rows.append([cell(item.get("source")), "changed", cell(item.get("reason"))])
    return table(["Source", "State", "Reason"], rows)


def absorb_legacy(text: str, section: str, block: str) -> str | None:
    """Replace a pre-fence heading + its table with a fenced block, in place.

    Only fires when the section body looks generated (a markdown table, an
    empty section, or a "None" placeholder) so hand-written narrative under
    one of these headings is never clobbered. Returns None if no legacy
    heading is found or its body looks like prose.
    """
    pattern = re.compile(
        r"^##[ \t]+" + LEGACY[section] + r"\b[^\n]*\n(?P<body>.*?)(?=^##[ \t]|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    body = match.group("body")
    looks_generated = (not body.strip()) or ("|" in body) or ("None" in body)
    if not looks_generated:
        return None
    replacement = f"{HEADINGS[section]}\n\n{block}\n\n"
    return text[:match.start()] + replacement + text[match.end():]


def splice(text: str, section: str, body: str) -> str:
    begin, end = f"<!-- BEGIN:{section} -->", f"<!-- END:{section} -->"
    block = f"{begin}\n{body}\n{end}"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    absorbed = absorb_legacy(text, section, block)
    if absorbed is not None:
        return absorbed
    heading = HEADINGS[section]
    return text.rstrip() + f"\n\n{heading}\n\n{block}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vault", nargs="?", default=".")
    parser.add_argument("--unprocessed", help="JSON output from check-sources.py")
    parser.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    index_path = vault / "Wiki" / "index.md"
    if not index_path.parent.is_dir():
        print(f"error: {index_path.parent} does not exist", file=sys.stderr)
        return 2

    payload = None
    if args.unprocessed:
        try:
            payload = json.loads(Path(args.unprocessed).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: could not read --unprocessed: {exc}", file=sys.stderr)

    text = index_path.read_text(encoding="utf-8") if index_path.exists() else (
        "---\ntype: index\ntags:\n  - wiki/index\n---\n\n# Wiki Index\n"
    )

    builders = {
        "sources": lambda: build_sources(vault),
        "entities": lambda: build_entities(vault),
        "concepts": lambda: build_concepts(vault),
        "synthesis": lambda: build_synthesis(vault),
        "unprocessed": lambda: build_unprocessed(payload),
    }
    for section in SECTIONS:
        text = splice(text, section, builders[section]())

    if args.dry_run:
        print(text)
        return 0

    index_path.write_text(text, encoding="utf-8")
    counts = {f: len(collect(vault, f)) for f in ("sources", "entities", "concepts", "synthesis")}
    summary = ", ".join(f"{v} {k}" for k, v in counts.items())
    print(f"Rebuilt {index_path.relative_to(vault)} — {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
