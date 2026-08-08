# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
verify-grounding.py — check that every `realized_by` symbol actually exists.

The code wiki's central claim is that entity and concept pages are grounded in
real code, not in plausible-sounding architecture the model invented. That claim
is only worth anything if something checks it, so this does:

    every string in a page's `realized_by:` list
      must appear in the codegraph index
        as nodes.qualified_name (a symbol) or files.path (a whole file)

Anything that doesn't match is a hallucinated symbol, a typo, or — most often
in practice — a page that went stale when the code was renamed underneath it.
All three are the same failure from a reader's perspective: a page claiming
grounding it does not have.

Both forms are legal in `realized_by`. Symbols are the norm and should be
preferred; a bare file path is the honest fallback for a page grounded in a file
whose contents the extractor could not name (anonymous callbacks, a config that
is one arrow function), where the alternative is inventing a symbol.

Exit codes make this usable as a gate:
    0   every symbol resolved
    1   at least one did not
    2   bad invocation (no index, no Wiki/)

Usage:
    uv run verify-grounding.py <repo>
    uv run verify-grounding.py <repo> --json
    uv run verify-grounding.py <repo> --db /path/to/codegraph.db
    uv run verify-grounding.py <repo> --strict     # also flag file-path grounding
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import yaml

DEFAULT_DB = ".codegraph/codegraph.db"
GROUNDED_DIRS = ("entities", "concepts")


def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter of a markdown file as a dict (or {})."""
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


def index_names(db_path: Path) -> tuple[set[str], set[str]]:
    """(symbol qualified_names, file paths) known to the codegraph index.

    `kind='file'` nodes are excluded from the symbol set on purpose. codegraph
    emits one per indexed file with `qualified_name` set to the path itself, so
    counting them as symbols would make file-path grounding indistinguishable
    from real symbol grounding — and --strict, whose whole job is telling those
    apart, would silently never fire.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        symbols = {
            r[0] for r in conn.execute(
                "SELECT qualified_name FROM nodes WHERE kind != 'file'"
            ) if r[0]
        }
        files = {r[0] for r in conn.execute("SELECT path FROM files") if r[0]}
    finally:
        conn.close()
    return symbols, files


def check(repo: Path, symbols: set[str], files: set[str]) -> dict:
    """Resolve every realized_by entry; bucket into symbol / file / missing.

    Pure classification — deciding which buckets constitute failure is policy and
    lives in main(), so the same result can be judged against a different bar.
    """
    pages = missing = 0
    by_file, missing_rows, ungrounded = [], [], []
    total = 0

    for folder in GROUNDED_DIRS:
        directory = repo / "Wiki" / folder
        if not directory.is_dir():
            continue
        for page in sorted(directory.glob("*.md")):
            fm = parse_frontmatter(page)
            grounded = fm.get("realized_by") or []
            if not isinstance(grounded, list):
                grounded = [grounded]
            rel = f"Wiki/{folder}/{page.name}"

            if not grounded:
                ungrounded.append(rel)
                continue

            for name in grounded:
                name = str(name)
                total += 1
                if name in symbols:
                    continue
                if name in files:
                    by_file.append({"page": rel, "name": name})
                else:
                    missing += 1
                    missing_rows.append({"page": rel, "name": name})
            pages += 1

    return {
        "pages_checked": pages,
        "total": total,
        "resolved": total - missing,
        "missing": missing_rows,
        "file_grounded": by_file,
        "ungrounded_pages": ungrounded,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--db", help="codegraph db path (default <repo>/%s)" % DEFAULT_DB)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat file-path grounding as a failure (symbols only)",
    )
    parser.add_argument(
        "--allow-ungrounded",
        action="store_true",
        help="report pages with no realized_by instead of failing on them",
    )
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve() if args.db else repo / DEFAULT_DB

    if not db_path.exists():
        print(f"error: codegraph index not found at {db_path}", file=sys.stderr)
        print(f"       run `codegraph init --index {repo}` first, or pass --db", file=sys.stderr)
        return 2
    if not (repo / "Wiki").is_dir():
        print(f"error: {repo / 'Wiki'} not found — nothing to verify", file=sys.stderr)
        return 2

    symbols, files = index_names(db_path)
    result = check(repo, symbols, files)

    # Policy: what counts as failure. An ungrounded page fails by default —
    # SKILL.md lists it as one of three failure outcomes, and a page claiming
    # nothing is the one case the Symbols column cannot warn a reader about.
    result["ok"] = not (
        result["missing"]
        or (args.strict and result["file_grounded"])
        or (not args.allow_ungrounded and result["ungrounded_pages"])
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if result["total"] == 0:
        print("No realized_by symbols found — nothing to verify.")
        return 0

    print(f"{result['resolved']}/{result['total']} realized_by symbols "
          f"resolved across {result['pages_checked']} page(s)")

    if result["missing"]:
        print(f"\nMISSING — not in the index ({len(result['missing'])}):")
        for m in result["missing"]:
            print(f"  ✗ {m['page']}  ->  {m['name']}")

    if result["file_grounded"]:
        label = "REJECTED under --strict" if args.strict else "grounded by file, not symbol"
        print(f"\n{label} ({len(result['file_grounded'])}):")
        for m in result["file_grounded"]:
            print(f"  ~ {m['page']}  ->  {m['name']}")

    if result["ungrounded_pages"]:
        label = "reported only (--allow-ungrounded)" if args.allow_ungrounded else "FAIL"
        print(f"\nNo realized_by at all — {label} ({len(result['ungrounded_pages'])}):")
        for p in result["ungrounded_pages"]:
            print(f"  ? {p}")

    if result["ok"]:
        print("\nOK — every page is grounded in the index.")
        return 0

    print("\nFAIL — see above. Re-index if the code moved; fix the page if it did not.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
