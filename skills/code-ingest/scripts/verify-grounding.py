#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
verify-grounding.py — check that a code wiki still matches the code.

Two checks, both answering "does this page still describe reality?"

  1. every `realized_by` symbol exists in the index
  2. every `file:line` citation in prose still points where the sentence says

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

The second check exists because line numbers rot differently from names. A
rename breaks `realized_by` loudly and check (1) catches it. But inserting six
lines above a function silently shifts every citation below it: each one still
resolves, still lands inside the file, still points at *something* — just no
longer at what the sentence claims. Nothing else in the pipeline notices, and a
confidently wrong line number is worse than none.

So a citation is judged against the symbols named near it (same paragraph, plus
the page's own title). If any of them sits at the cited line, the citation is
corroborated; if every one points elsewhere, it is stale. Citations with no
named symbol to check against are left alone — prose legitimately points at a
statement or a comment, and this deliberately under-reports rather than crying
wolf. Fenced code blocks are skipped: a citation in a snippet is illustration,
not a claim.

Exit codes make this usable as a gate:
    0   everything resolved
    1   a symbol is missing, or a citation is stale
    2   bad invocation (no index, no Wiki/)

Usage:
    uv run verify-grounding.py <repo>
    uv run verify-grounding.py <repo> --json
    uv run verify-grounding.py <repo> --db /path/to/codegraph.db
    uv run verify-grounding.py <repo> --strict          # also flag file-path grounding
    uv run verify-grounding.py <repo> --no-line-refs    # symbols only
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import yaml

DEFAULT_DB = ".codegraph/codegraph.db"
GROUNDED_DIRS = ("entities", "concepts")

# A `path/to/file.ext:123` citation in prose. The "/" requirement is what keeps
# version strings ("v1.3.0:") and bare words out; a citation worth checking is
# always repo-relative.
CITATION = re.compile(r"(?<![\w/])([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.[A-Za-z0-9]+):(\d+)")

# Identifiers named near a citation: `symbol`, `symbol()`, `Class::method`, or
# [[Entity]]. The optional trailing "()" matters — prose naturally writes
# `resolvePluginDir()` for a function, and requiring a bare identifier silently
# skipped exactly the citations most worth checking.
ANCHOR = re.compile(
    r"`(?:[A-Za-z_][A-Za-z0-9_]*::)?([A-Za-z_][A-Za-z0-9_]*)(?:\([^`]*\))?`|\[\[([^\]|#]+)"
)

FENCE = re.compile(r"^\s*(```|~~~)")


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


def symbol_lines(conn: sqlite3.Connection) -> dict[tuple[str, str], set[int]]:
    """(file_path, symbol name) -> every line that name is defined on in that file.

    A set rather than an int because one name can legitimately appear more than
    once per file — two classes each with a `constructor`, an overload pair.
    """
    out: dict[tuple[str, str], set[int]] = {}
    for path, name, line in conn.execute(
        "SELECT file_path, name, start_line FROM nodes WHERE start_line IS NOT NULL"
    ):
        if path and name:
            out.setdefault((str(path), str(name)), set()).add(int(line))
    return out


def prose_paragraphs(text: str):
    """Yield (first_line_number, paragraph_text), skipping fenced code blocks.

    Paragraphs, not physical lines: this prose is hard-wrapped, so a symbol and
    the citation that belongs to it routinely land on different lines —

        ... a numbered ten-step sequence in `startSession`
        (`src/main.ts:75`) and its mirror in `stopSession` ...

    Splitting by line would divorce `startSession` from `:75` and report a
    correct citation as stale. A blank-line-delimited block is the smallest unit
    that reliably holds a claim and its evidence together.

    Citations inside a fence are usually illustrative — a snippet showing what
    the code looks like, not a claim about where it lives — so fences are
    skipped rather than flagged.
    """
    in_fence, buf, start = False, [], 1
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            yield start, "\n".join(buf)
            buf = []
    if buf:
        yield start, "\n".join(buf)


def check_citations(repo: Path, indexed_files: set[str],
                    sym_lines: dict[tuple[str, str], set[int]]) -> list[dict]:
    """Flag `file:line` citations in prose that the index contradicts.

    Three failures, in increasing subtlety:

      unknown-file  the cited path is not indexed — renamed, deleted, or a typo
      out-of-range  the line is past the end of the file
      stale-anchor  a symbol named in the same prose line really exists in that
                    file, but at a different line

    The third is the one that matters. Line numbers drift silently whenever code
    is inserted above them: every citation stays inside the file and keeps
    pointing at something, just no longer at what the sentence says. Anchoring
    the check to a nearby symbol name is what makes that detectable — a bare
    range check never would.

    Citations that resolve to no named symbol are left alone. Prose legitimately
    points at a statement or a comment, and demanding a symbol at every cited
    line would bury the real findings.
    """
    findings = []
    line_counts: dict[str, int] = {}

    for page in sorted(repo.joinpath("Wiki").rglob("*.md")):
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel_page = str(page.relative_to(repo))

        # An entity page's own title is an implicit anchor. "Defined at
        # `src/main.ts:19`" on SpectreTerminalView.md is anchored by the page
        # subject, which the sentence has no reason to repeat.
        page_anchor = str(parse_frontmatter(page).get("title") or page.stem).strip()

        for lineno, line in prose_paragraphs(text):
            for path, cited in CITATION.findall(line):
                cited = int(cited)
                base = {"page": rel_page, "page_line": lineno,
                        "path": path, "cited_line": cited}

                if path not in indexed_files:
                    findings.append({**base, "kind": "unknown-file",
                                     "detail": "path is not in the codegraph index"})
                    continue

                if path not in line_counts:
                    try:
                        line_counts[path] = len(
                            repo.joinpath(path).read_text(encoding="utf-8").splitlines()
                        )
                    except (OSError, UnicodeDecodeError):
                        line_counts[path] = -1
                total = line_counts[path]
                if total >= 0 and cited > total:
                    findings.append({**base, "kind": "out-of-range",
                                     "detail": f"file has {total} lines"})
                    continue

                # A prose line often carries several citations and several
                # anchors — "startSession (src/main.ts:75) and its mirror
                # stopSession (src/main.ts:186)". Which anchor belongs to which
                # citation is not recoverable from the text, so the rule is: if
                # ANY named symbol on this line sits at the cited line, the
                # citation is corroborated. Only when every known anchor points
                # elsewhere is it stale. Erring toward silence is deliberate — a
                # gate that cries wolf gets ignored, and this one has to survive
                # every re-ingest.
                candidates = {}
                names = [(a or b).strip() for a, b in ANCHOR.findall(line)]
                names.append(page_anchor)
                for name in names:
                    actual = sym_lines.get((path, name))
                    if actual:
                        candidates[name] = actual

                if candidates and not any(cited in v for v in candidates.values()):
                    name, actual = min(candidates.items(),
                                       key=lambda kv: min(abs(n - cited) for n in kv[1]))
                    findings.append({
                        **base, "kind": "stale-anchor", "symbol": name,
                        "detail": f"`{name}` is at "
                                  f"{', '.join(str(n) for n in sorted(actual))}",
                    })
    return findings


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
    parser.add_argument(
        "--no-line-refs",
        action="store_true",
        help="skip checking `file:line` citations in prose",
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

    result["citations"] = []
    if not args.no_line_refs:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            result["citations"] = check_citations(repo, files, symbol_lines(conn))
        finally:
            conn.close()

    # Policy: what counts as failure. An ungrounded page fails by default —
    # SKILL.md lists it as one of three failure outcomes, and a page claiming
    # nothing is the one case the Symbols column cannot warn a reader about.
    result["ok"] = not (
        result["missing"]
        or result["citations"]
        or (args.strict and result["file_grounded"])
        or (not args.allow_ungrounded and result["ungrounded_pages"])
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if result["total"] == 0 and not result["citations"]:
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

    if result["citations"]:
        print(f"\nSTALE LINE REFERENCES ({len(result['citations'])}):")
        for c in result["citations"]:
            print(f"  ✗ {c['page']}:{c['page_line']}  cites {c['path']}:{c['cited_line']}"
                  f"  [{c['kind']}] — {c['detail']}")

    if result["ok"]:
        print("\nOK — every page is grounded in the index.")
        return 0

    print("\nFAIL — see above. Re-index if the code moved; fix the page if it did not.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
