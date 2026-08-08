# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
scaffold-sources.py — generate Wiki/sources/ pages from the codegraph index.

Everything on a source page that the graph already knows should come from the
graph, not from a model retyping it. This script writes those parts:

    frontmatter    source_path, source_hash, language, dates
    Key Symbols    kind / name / signature / line, from nodes
    Depends On     outbound `calls` + `imports` edges
    Used By        inbound `calls` edges from other files

and leaves the parts it cannot know — Purpose, Notes — as prose for a human or
model to write. Re-running regenerates only the generated blocks; prose is
preserved verbatim.

That split is the point. Hashes and symbol tables are the parts that go
silently stale and that nobody proofreads, so they are mechanical and
reproducible: same index in, same bytes out. Judgement about *why* a file
exists is the part worth a model's attention, so it gets a slot instead of a
guess.

Generated regions are fenced with the same markers rebuild-index.py uses:

    <!-- BEGIN:symbols --> ... <!-- END:symbols -->
    <!-- BEGIN:depends --> ... <!-- END:depends -->
    <!-- BEGIN:usedby -->  ... <!-- END:usedby -->

Anything outside a fence survives regeneration untouched. A page whose fence has
gone missing is repaired by appending the block under its canonical heading —
never by writing a fresh `source_hash` over a section that did not regenerate,
which would assert the page is current when it is not. Pages are matched to
files by `source_path` in frontmatter, not by filename, so renaming a page does
not orphan it.

Usage:
    uv run scaffold-sources.py <repo>
    uv run scaffold-sources.py <repo> --dry-run
    uv run scaffold-sources.py <repo> --only 'src/**'
    uv run scaffold-sources.py <repo> --db /path/to/codegraph.db
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import yaml

DEFAULT_DB = ".codegraph/codegraph.db"

# Symbol kinds worth listing. `constant` is included deliberately: module-level
# constants are frequently the real API surface (view types, ids, config keys),
# and omitting them silently drops a file's most-referenced names. Keep in sync
# with seed-areas.py:KIND_RANK, which ranks the same vocabulary.
SYMBOL_KINDS = ("class", "interface", "type_alias", "function", "method", "constant")

# Ordering for the symbol table: declaration order within a file is the most
# readable grouping, so this only breaks ties for same-line rows.
KIND_RANK = {"class": 0, "interface": 1, "type_alias": 2, "function": 3,
             "method": 4, "constant": 5}

# Fenced sections, and the heading each belongs under when a page needs repair.
SECTIONS = {"symbols": "## Key Symbols",
            "depends": "## Depends On",
            "usedby": "## Used By"}

PROSE_PURPOSE = "_TODO — 2–3 sentences: what this file is for, and why it exists._"
PROSE_NOTES = "_TODO — what the graph cannot say: gotchas, contradictions, dead code._"


# --- index reads --------------------------------------------------------------
#
# Every edge query writes `+e.kind` rather than `e.kind`. The unary plus stops
# SQLite considering idx_edges_kind, which looks usable but is catastrophic
# here: 'calls' is the single largest edge kind, so seeking on it scans nearly
# every edge in the database — once per file. Measured on a 275-file repo with
# no ANALYZE stats present, that is 8.6s versus 38ms. codegraph does run
# `PRAGMA optimize` after indexing, but it swallows failures and we open the DB
# read-only, so this script cannot detect or repair missing stats. Suppressing
# the bad index costs ~10% when stats exist and removes a 227x cliff when they
# don't.

def connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def indexed_files(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return conn.execute(
        "SELECT path, content_hash, language FROM files ORDER BY path"
    ).fetchall()


def symbols_for(conn: sqlite3.Connection, path: str) -> list[tuple]:
    placeholders = ",".join("?" for _ in SYMBOL_KINDS)
    rows = conn.execute(
        f"""SELECT kind, name, signature, start_line
              FROM nodes
             WHERE file_path = ? AND kind IN ({placeholders})""",
        (path, *SYMBOL_KINDS),
    ).fetchall()
    rows.sort(key=lambda r: (r[3] if r[3] is not None else 0,
                             KIND_RANK.get(r[0], 9), r[1]))
    return rows


def outbound_calls(conn: sqlite3.Connection, path: str) -> list[tuple]:
    """(caller, callee, callee_file, call_sites) for calls leaving this file's symbols.

    Grouped rather than DISTINCT so the call-site count survives. Multiplicity is
    signal: the helper invoked 21 times is the file's workhorse, and collapsing
    that to a bare edge throws the information away.
    """
    return conn.execute(
        """SELECT s.name, t.name, t.file_path, COUNT(*) AS sites
             FROM edges e
             JOIN nodes s ON e.source = s.id
             JOIN nodes t ON e.target = t.id
            WHERE +e.kind = 'calls' AND s.file_path = ?
            GROUP BY s.name, t.name, t.file_path
            ORDER BY sites DESC, s.name, t.name""",
        (path,),
    ).fetchall()


def inbound_calls(conn: sqlite3.Connection, path: str) -> list[tuple]:
    """(caller, caller_file, callee, call_sites) for calls into this file from elsewhere."""
    return conn.execute(
        """SELECT s.name, s.file_path, t.name, COUNT(*) AS sites
             FROM edges e
             JOIN nodes s ON e.source = s.id
             JOIN nodes t ON e.target = t.id
            WHERE +e.kind = 'calls' AND t.file_path = ? AND s.file_path != ?
            GROUP BY s.name, s.file_path, t.name
            ORDER BY s.file_path, s.name""",
        (path, path),
    ).fetchall()


def imports_for(conn: sqlite3.Connection, path: str) -> list[str]:
    return [
        name for (name,) in conn.execute(
            """SELECT DISTINCT t.name FROM edges e
                 JOIN nodes s ON e.source = s.id
                 JOIN nodes t ON e.target = t.id
                WHERE +e.kind = 'imports' AND s.file_path = ?
                ORDER BY t.name""",
            (path,),
        ) if name
    ]


# --- rendering ----------------------------------------------------------------

def slug_for(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-")


def cell(value) -> str:
    """Render a value as a table cell, escaping pipes. Mirrors rebuild-index.py:cell."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def table(header: list[str], rows: list[list[str]]) -> str:
    """Markdown table. Mirrors rebuild-index.py:table, minus the empty placeholder —
    callers here supply their own, more specific empty-state prose."""
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# Signatures are whatever the extractor captured, which for an initialized
# constant is the entire initializer — an inline SVG or a base64 blob will
# otherwise land in one table cell and destroy the page. Truncate for display;
# the file itself remains the source of truth.
SIG_MAX = 80


def sig(value) -> str:
    text = cell(value)
    if not text:
        return "—"
    text = re.sub(r"\s+", " ", text)
    if len(text) > SIG_MAX:
        text = text[: SIG_MAX - 1].rstrip() + "…"
    return text


def render_symbols(rows: list[tuple]) -> str:
    if not rows:
        return (
            "_No named symbols indexed._ The extractor found nothing to name in "
            "this file — typically anonymous callbacks (`describe`/`it` bodies, a "
            "config passed as an arrow function). This file can ground no entity; "
            "describe it in prose instead."
        )
    return table(
        ["Kind", "Symbol", "Signature", "Line"],
        [[cell(kind), f"`{cell(name)}`", f"`{sig(signature)}`", cell(line)]
         for kind, name, signature, line in rows],
    )


def render_depends(calls: list[tuple], imports: list[str], path: str) -> str:
    blocks = []
    external = [c for c in calls if c[2] != path]
    internal = [c for c in calls if c[2] == path]

    if external:
        blocks.append("**Calls into other files**\n\n" + table(
            ["Caller", "Callee", "Defined in", "Sites"],
            [[f"`{cell(caller)}`", f"`{cell(callee)}`", cell(cfile), cell(sites)]
             for caller, callee, cfile, sites in external],
        ))

    if internal:
        blocks.append("**Internal calls**\n\n" + table(
            ["Caller", "Callee", "Sites"],
            [[f"`{cell(caller)}`", f"`{cell(callee)}`", cell(sites)]
             for caller, callee, _cfile, sites in internal],
        ))

    if imports:
        blocks.append("**Imports** — " + ", ".join(f"`{cell(m)}`" for m in imports))
        blocks.append(
            "_Static `imports` edges only. A `await import(...)` produces no edge, "
            "so dynamically-coupled files look unrelated here._"
        )

    return "\n\n".join(blocks) if blocks else "_No outbound edges indexed._"


def render_usedby(rows: list[tuple]) -> str:
    if not rows:
        return "_No inbound calls indexed._ Either an entrypoint, or reached only dynamically."
    return table(
        ["Caller", "Defined in", "Calls", "Sites"],
        [[f"`{cell(caller)}`", cell(cfile), f"`{cell(callee)}`", cell(sites)]
         for caller, cfile, callee, sites in rows],
    )


# --- page assembly ------------------------------------------------------------

def splice(text: str, section: str, body: str) -> tuple[str, bool]:
    """Replace the fenced block for `section`. Returns (text, repaired).

    A missing fence is repaired by appending the block under its canonical
    heading, the same self-healing rebuild-index.py:splice does. The
    alternative — skipping the section but writing the page anyway — would
    stamp a fresh source_hash onto content that never regenerated, and
    check-sources.py would then report the page unchanged forever.
    """
    begin, end = f"<!-- BEGIN:{section} -->", f"<!-- END:{section} -->"
    block = f"{begin}\n{body}\n{end}"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1), False
    return text.rstrip() + f"\n\n{SECTIONS[section]}\n\n{block}\n", True


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a page into (frontmatter, body). Invalid frontmatter yields ({}, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), parts[2].lstrip("\n")


def build_frontmatter(existing: dict, path: str, content_hash: str,
                      language: str, today: str) -> dict:
    """Refresh the keys this script owns, preserving every other key on the page.

    `dict(existing)` first, then overwrite: title, area tags, and any field added
    by hand survive regeneration. Only type/source_*/language are ours.
    """
    fm = dict(existing)
    fm["type"] = "source-summary"
    fm.setdefault("title", path)
    fm["source_kind"] = "file"
    fm["source_path"] = path
    fm["source_hash"] = content_hash
    fm["language"] = language
    fm.setdefault("date_ingested", today)
    if existing and existing.get("source_hash") != content_hash:
        fm["date_updated"] = today
    tags = fm.get("tags") or []
    if "wiki/source" not in tags:
        tags = ["wiki/source", *tags]
    fm["tags"] = tags
    return fm


def with_frontmatter(fm: dict, body: str) -> str:
    front = yaml.dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{front}\n---\n\n{body.lstrip()}"


def new_body(path: str, symbols: str, depends: str, usedby: str) -> str:
    def fenced(section: str, content: str) -> str:
        return f"<!-- BEGIN:{section} -->\n{content}\n<!-- END:{section} -->"

    return f"""# {path}

## Purpose

{PROSE_PURPOSE}

{SECTIONS["symbols"]}

{fenced("symbols", symbols)}

{SECTIONS["depends"]}

{fenced("depends", depends)}

{SECTIONS["usedby"]}

{fenced("usedby", usedby)}

## Notes

{PROSE_NOTES}

## Raw Source

`{path}`
"""


# --- main ---------------------------------------------------------------------

def existing_pages(repo: Path) -> dict[str, tuple[Path, dict, str]]:
    """Map source_path -> (page, frontmatter, body).

    Keyed on frontmatter rather than filename so a renamed page is not orphaned.
    Returns the parsed halves so main() never re-reads or re-parses a page it
    has already opened.
    """
    out: dict[str, tuple[Path, dict, str]] = {}
    directory = repo / "Wiki" / "sources"
    if not directory.is_dir():
        return out
    for page in sorted(directory.glob("*.md")):
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm, body = parse_frontmatter(text)
        src = fm.get("source_path")
        if src:
            out[str(src)] = (page, fm, body)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--db", help="codegraph db path (default <repo>/%s)" % DEFAULT_DB)
    parser.add_argument("--only", action="append", default=[],
                        help="glob to restrict which indexed files are scaffolded (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--today", help="override the date stamp (for reproducible runs)")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve() if args.db else repo / DEFAULT_DB
    if not db_path.exists():
        print(f"error: codegraph index not found at {db_path}", file=sys.stderr)
        print(f"       run `codegraph init --index {repo}` first, or pass --db", file=sys.stderr)
        return 2

    today = args.today or date.today().isoformat()
    pages = existing_pages(repo)
    out_dir = repo / "Wiki" / "sources"
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        files = indexed_files(conn)
        if args.only:
            files = [f for f in files if any(fnmatch.fnmatch(f[0], p) for p in args.only)]

        created = updated = 0
        repaired: list[str] = []

        for path, content_hash, language in files:
            symbols = render_symbols(symbols_for(conn, path))
            depends = render_depends(outbound_calls(conn, path), imports_for(conn, path), path)
            usedby = render_usedby(inbound_calls(conn, path))

            entry = pages.get(path)
            if entry:
                page, old_fm, body = entry
                fixed = []
                for section, content in (("symbols", symbols),
                                         ("depends", depends),
                                         ("usedby", usedby)):
                    body, was_repaired = splice(body, section, content)
                    if was_repaired:
                        fixed.append(section)
                if fixed:
                    repaired.append(f"{page.name}: re-added {', '.join(fixed)}")
                fm = build_frontmatter(old_fm, path, content_hash, language, today)
                rendered, target, action = with_frontmatter(fm, body), page, "update"
                updated += 1
            else:
                fm = build_frontmatter({}, path, content_hash, language, today)
                rendered = with_frontmatter(fm, new_body(path, symbols, depends, usedby))
                target = out_dir / f"{slug_for(path)}.md"
                action = "create"
                created += 1

            if args.dry_run:
                print(f"  {action:6s} {target.relative_to(repo)}")
            else:
                target.write_text(rendered, encoding="utf-8")
    finally:
        conn.close()

    suffix = " (dry run, nothing written)" if args.dry_run else ""
    print(f"{created} created, {updated} updated{suffix}")

    if repaired:
        print("\nMissing fences repaired — check the section landed where you want it:")
        for r in repaired:
            print(f"  ~ {r}")

    if not args.dry_run and (created or updated):
        print("\nNext: fill the Purpose/Notes prose, then run verify-grounding.py "
              "and rebuild-index.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
