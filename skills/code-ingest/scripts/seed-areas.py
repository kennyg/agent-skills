# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
seed-areas.py — propose Wiki/code-areas.yml from the codegraph index.

An "area" is a coarse chunk of the codebase the wiki organises around. Two
ways to derive them, in priority order:

  routes   If the framework resolver emitted `route` nodes (SvelteKit, Nuxt,
           Vue pages, Express/Nest handlers, ...), group by the first segment
           of each route path. Routes are the app's real seams — far better
           than folders for a web app, where one feature spans components,
           loaders, and endpoints in different directories.

  modules  Otherwise, fall back to module boundaries read from the graph.
           Directory *enumeration* would either bury everything under one
           giant `src/` or explode into every leaf folder; instead we split
           only the top-level dirs that are large enough to warrant it, so a
           library like codegraph itself yields ~a dozen sensible modules.

This does not decide the taxonomy for you — it seeds a file you then edit.
Re-running regenerates the `areas:` list. Always review with --dry-run first.

Usage:
    uv run seed-areas.py <repo> --dry-run
    uv run seed-areas.py <repo>
    uv run seed-areas.py <repo> --db /path/to/codegraph.db --split-threshold 15
"""

from __future__ import annotations

import argparse
import fnmatch
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import yaml

DEFAULT_DB = ".codegraph/codegraph.db"
ROOT = "<root>"
KIND_RANK = {"class": 0, "interface": 1, "type_alias": 2, "function": 3, "method": 4}


def connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


# --- routes -------------------------------------------------------------------

def route_areas(conn: sqlite3.Connection, excludes: list[str]) -> list[dict] | None:
    rows = conn.execute(
        "SELECT name, file_path FROM nodes WHERE kind='route' ORDER BY name"
    ).fetchall()
    if not rows:
        return None
    groups: dict[str, dict] = {}
    for name, file_path in rows:
        segment = "/" + (name.strip("/").split("/", 1)[0] if name.strip("/") else "")
        g = groups.setdefault(segment, {"routes": set(), "files": set()})
        g["routes"].add(name)
        if file_path and not excluded(file_path, excludes):
            g["files"].add(file_path)
    areas = []
    for segment, g in sorted(groups.items()):
        areas.append({
            "name": segment,
            "kind": "route-group",
            "routes": sorted(g["routes"]),
            "files": sorted(g["files"]),
        })
    return areas


# --- modules (fallback) -------------------------------------------------------

def top_dir(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else ROOT


def area_key(path: str, split_tops: set[str]) -> str:
    """A file's module key: second-level dir inside a split top, else the top."""
    parts = path.split("/")
    if len(parts) == 1:
        return ROOT
    top = parts[0]
    if top in split_tops and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return top


def key_symbols(conn: sqlite3.Connection, files: list[str], limit: int = 6) -> list[str]:
    placeholders = ",".join("?" for _ in files)
    rows = conn.execute(
        f"""SELECT name, kind FROM nodes
            WHERE file_path IN ({placeholders})
              AND is_exported=1
              AND kind IN ('class','interface','type_alias','function','method')""",
        files,
    ).fetchall()
    rows.sort(key=lambda r: (KIND_RANK.get(r[1], 9), r[0]))
    seen, out = set(), []
    for name, _kind in rows:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def module_areas(conn: sqlite3.Connection, split_threshold: int, excludes: list[str]) -> list[dict]:
    files = [r[0] for r in conn.execute("SELECT path FROM files").fetchall()
             if not excluded(r[0], excludes)]

    top_counts: dict[str, int] = defaultdict(int)
    top_has_subdirs: dict[str, bool] = defaultdict(bool)
    for path in files:
        top = top_dir(path)
        top_counts[top] += 1
        if path.count("/") >= 2:
            top_has_subdirs[top] = True
    split_tops = {
        t for t, n in top_counts.items()
        if n > split_threshold and top_has_subdirs[t]
    }

    buckets: dict[str, list[str]] = defaultdict(list)
    for path in files:
        buckets[area_key(path, split_tops)].append(path)

    areas = []
    for key in sorted(buckets):
        members = sorted(buckets[key])
        langs = sorted({
            r[0] for r in conn.execute(
                f"SELECT DISTINCT language FROM files WHERE path IN ({','.join('?' for _ in members)})",
                members,
            ).fetchall()
        })
        name = ROOT.strip("<>") if key == ROOT else key.split("/")[-1]
        areas.append({
            "name": name,
            "kind": "module",
            "path": "." if key == ROOT else key,
            "files": len(members),
            "languages": langs,
            "key_symbols": key_symbols(conn, members),
        })
    return areas


def render(source: str, areas: list[dict]) -> str:
    header = (
        "# Wiki/code-areas.yml — coarse map of the codebase.\n"
        "# Generated by seed-areas.py from the codegraph index.\n"
        f"# Derived from: {source}. Re-running regenerates `areas:`; edit names/notes freely.\n\n"
    )
    body = yaml.safe_dump(
        {"source": source, "generated_from": "codegraph", "areas": areas},
        sort_keys=False, allow_unicode=True, default_flow_style=False,
    )
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--db", help="codegraph db path (default <repo>/%s)" % DEFAULT_DB)
    parser.add_argument("--split-threshold", type=int, default=15,
                        help="split a top-level dir into submodules past this many files")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="drop files matching this glob (repeatable), e.g. --exclude '__tests__/*'")
    parser.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve() if args.db else repo / DEFAULT_DB
    if not db_path.exists():
        print(f"error: codegraph index not found at {db_path}", file=sys.stderr)
        return 2

    conn = connect(db_path)
    try:
        areas = route_areas(conn, args.exclude)
        source = "routes"
        if areas is None:
            areas = module_areas(conn, args.split_threshold, args.exclude)
            source = "modules"
    finally:
        conn.close()

    output = render(source, areas)

    if args.dry_run:
        print(output)
        print(f"# --- {len(areas)} areas from {source} (dry run, not written) ---", file=sys.stderr)
        return 0

    out_path = repo / "Wiki" / "code-areas.yml"
    if not out_path.parent.is_dir():
        print(f"error: {out_path.parent} does not exist (create the wiki first)", file=sys.stderr)
        return 2
    out_path.write_text(output, encoding="utf-8")
    print(f"Wrote {out_path.relative_to(repo)} — {len(areas)} areas from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
