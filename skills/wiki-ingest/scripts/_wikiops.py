"""Operations behind the wiki-ingest commands.

Each command script is a thin wrapper over a function here. `finalize-ingest.py`
calls the functions in one process, so the pages, hashes and queue are read once.
This module is not a command, so it has no shebang and no executable bit.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import _wikilib as wl

# --- index ----------------------------------------------------------------------

HEADINGS = {name: f"## {name.title()}" for name in wl.INDEX_SECTIONS}
# Legacy heading spellings to absorb in place, so a hand-written index
# migrates without duplicating its tables.
LEGACY = {name: name.title() for name in wl.INDEX_SECTIONS} | {"unprocessed": r"Unprocessed(?: Sources)?"}


def cell(value) -> str:
    """Render a frontmatter value as a table cell and escape pipes."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None yet._"
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def link(page: wl.Page) -> str:
    return f"[[{page.path.stem}]]"


def build_sources(vault: Path) -> str:
    rows = [
        [
            link(p),
            cell(wl.first(p.fm, "source_kind") or "file"),
            cell(p.fm.get("source_path")),
            cell(wl.first(p.fm, "date_ingested", "date_updated")),
        ]
        for p in wl.pages(vault, "sources")
    ]
    return table(["Source", "Kind", "Path", "Ingested"], rows)


def build_counted(vault: Path, folder: str, headers: list[str], key: str) -> str:
    """Table for entities or concepts. `key` is the kind or confidence column."""
    rows = []
    for p in wl.pages(vault, folder):
        grounded = p.fm.get("realized_by") or []
        rows.append(
            [
                link(p),
                cell(p.fm.get(key)),
                cell(p.fm.get("source_count") or 0),
                cell(len(grounded) if grounded else ""),
                cell(wl.first(p.fm, "date_updated", "date_created")),
            ]
        )
    return table(headers, rows)


def build_synthesis(vault: Path) -> str:
    rows = [
        [
            link(p),
            cell(wl.first(p.fm, "question", "query", "title")),
            cell(wl.first(p.fm, "date_updated", "date_created")),
        ]
        for p in wl.pages(vault, "synthesis")
    ]
    return table(["Page", "Question", "Updated"], rows)


def build_unprocessed(vault: Path) -> str:
    queue = wl.classify(vault)
    rows = [[cell(item["source"]), "new", ""] for item in queue["new"]]
    rows += [[cell(item["source"]), "changed", cell(item["reason"])] for item in queue["changed"]]
    return table(["Source", "State", "Reason"], rows)


def absorb_legacy(text: str, section: str, block: str) -> str | None:
    """Replace a legacy heading and its table with a fenced block.

    This only fires when the section body looks generated: a table, an empty
    body, or a "None" placeholder. Hand-written prose under the heading is
    never replaced.
    """
    pattern = re.compile(
        r"^##[ \t]+" + LEGACY[section] + r"\b[^\n]*\n(?P<body>.*?)(?=^##[ \t]|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    body = match.group("body")
    if body.strip() and "|" not in body and "None" not in body:
        return None
    return text[: match.start()] + f"{HEADINGS[section]}\n\n{block}\n\n" + text[match.end() :]


def splice(text: str, section: str, body: str) -> str:
    begin, end = f"<!-- BEGIN:{section} -->", f"<!-- END:{section} -->"
    block = f"{begin}\n{body}\n{end}"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    absorbed = absorb_legacy(text, section, block)
    if absorbed is not None:
        return absorbed
    return text.rstrip() + f"\n\n{HEADINGS[section]}\n\n{block}\n"


def render_index(vault: Path) -> tuple[str, str]:
    """Return (current text, regenerated text) of Wiki/index.md."""
    path = vault / "Wiki" / "index.md"
    current = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else "---\ntype: wiki-index\ndate_updated: 2000-01-01\n---\n\n# Wiki Index\n"
    )
    bodies = {
        "sources": build_sources(vault),
        "entities": build_counted(
            vault, "entities", ["Entity", "Kind", "Sources", "Symbols", "Updated"], "entity_kind"
        ),
        "concepts": build_counted(
            vault, "concepts", ["Concept", "Confidence", "Sources", "Symbols", "Updated"], "confidence"
        ),
        "synthesis": build_synthesis(vault),
        "unprocessed": build_unprocessed(vault),
    }
    text = current
    for section in wl.INDEX_SECTIONS:
        text = splice(text, section, bodies[section])
    return current, text


def write_index(vault: Path) -> bool:
    """Rewrite Wiki/index.md. Return True when it changed."""
    current, text = render_index(vault)
    if text == current:
        return False
    try:
        text = wl.set_frontmatter_value(text, "date_updated", wl.today())
    except ValueError:
        pass
    (vault / "Wiki" / "index.md").write_text(text, encoding="utf-8")
    return True


# --- overview -------------------------------------------------------------------


def overview_counts(vault: Path) -> dict[str, int]:
    paths = [str(p.fm.get("source_path", "")) for p in wl.pages(vault, "sources")]
    return {
        "sources": len(paths),
        "total": len(wl.raw_sources(vault)),
        "clippings": sum(p.startswith("Clippings/") for p in paths),
        "captures": sum(p.startswith("Twitter-Captures/") for p in paths),
        "entities": len(wl.pages(vault, "entities")),
        "concepts": len(wl.pages(vault, "concepts")),
        "synthesis": len(wl.pages(vault, "synthesis")),
    }


def overview_rules(c: dict[str, int]) -> list[tuple[str, str]]:
    return [
        (r"(This wiki synthesizes )\d+( sources)", rf"\g<1>{c['sources']}\g<2>"),
        (
            r"(`Clippings/` \()\d+(\) and `Twitter-Captures/` \()\d+(\))",
            rf"\g<1>{c['clippings']}\g<2>{c['captures']}\g<3>",
        ),
        (r"(\*\*)\d+( of )\d+(\*\* sources ingested)", rf"\g<1>{c['sources']}\g<2>{c['total']}\g<3>"),
        (
            r"(\*\*)\d+( entities\*\*, \*\*)\d+( concepts\*\* created)",
            rf"\g<1>{c['entities']}\g<2>{c['concepts']}\g<3>",
        ),
        (r"(\*\*)\d+( synthesis\*\* pages?)", rf"\g<1>{c['synthesis']}\g<2>"),
    ]


def rewrite_overview(text: str, counts: dict[str, int]) -> tuple[str, list[str]]:
    """Return (text with current counts, patterns that matched nothing).

    A pattern with no match means the overview prose was reworded. The caller
    must report it, or the count would drift without a warning.
    """
    unmatched = []
    for pattern, repl in overview_rules(counts):
        text, n = re.subn(pattern, repl, text, count=1)
        if n == 0:
            unmatched.append(pattern)
    return text, unmatched


def write_overview(vault: Path) -> tuple[bool, list[str]]:
    """Refresh the overview counts. Return (changed, unmatched patterns)."""
    path = vault / "Wiki" / "overview.md"
    current = path.read_text(encoding="utf-8")
    updated, unmatched = rewrite_overview(current, overview_counts(vault))
    if updated != current:
        path.write_text(wl.set_frontmatter_value(updated, "date_updated", wl.today()), encoding="utf-8")
    return updated != current, unmatched


# --- log ------------------------------------------------------------------------


def format_links(names: list[str]) -> str:
    return ", ".join(f"[[{n}]]" for n in sorted(names, key=str.casefold))


def build_log_entry(vault: Path, slug: str, date: str, notes: list[str]) -> str:
    fm = wl.parse_frontmatter(wl.source_page_path(vault, slug))
    raw = str(fm.get("source_path", "")).removesuffix(".md")
    found = wl.ingest_summary(vault, slug, date)
    lines = [f"## [{date}] ingest | {fm.get('title') or slug}", "", f"- Source: [[{raw}]]", wl.log_marker(slug)]
    for label, group, kind in (
        ("Created entities", "entities", "created"),
        ("Updated entities", "entities", "updated"),
        ("Created concepts", "concepts", "created"),
        ("Updated concepts", "concepts", "updated"),
    ):
        if found[group][kind]:
            lines.append(f"- {label}: {format_links(found[group][kind])}")
    lines += [f"- Note: {n}" for n in notes]
    return "\n".join(lines)


def append_log_entry(vault: Path, slug: str, date: str, notes: list[str]) -> bool:
    """Append the ingest entry. Return False when the source already has one."""
    log = vault / "Wiki" / "log.md"
    text = log.read_text(encoding="utf-8") if log.exists() else "---\ntype: wiki-log\n---\n\n# Wiki Log\n"
    if wl.has_log_entry(text, slug):
        return False
    entry = build_log_entry(vault, slug, date, notes)
    log.write_text(text.rstrip("\n") + "\n\n" + entry + "\n", encoding="utf-8")
    return True


# --- qmd ------------------------------------------------------------------------


def refresh_qmd() -> int:
    """Run `qmd update` and `qmd embed`. Skip with exit 0 when `qmd` is absent."""
    if shutil.which("qmd") is None:
        print("qmd not installed; search index not refreshed")
        return 0
    for step in ("update", "embed"):
        code = subprocess.run(["qmd", step], check=False).returncode
        if code != 0:
            print(f"error: qmd {step} failed with exit code {code}")
            return code
    print("qmd index refreshed")
    return 0


# --- validation -----------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED = {
    "source-summary": ("title", "source_path", "source_hash", "source_url", "author", "date_ingested", "tags"),
    "entity": ("title", "entity_kind", "date_created", "date_updated", "source_count", "tags"),
    "concept": ("title", "confidence", "date_created", "date_updated", "source_count", "tags"),
    "synthesis": ("title", "date_created", "query", "tags"),
}
DATE_KEYS = ("date_created", "date_updated", "date_ingested")
MISSING_OK = ("source_url", "author")  # may be empty for a clipping with no byline


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


def known_targets(vault: Path) -> set[str]:
    """Casefolded names a wikilink may resolve to: file names and vault paths."""
    names = set()
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in {".git", ".obsidian"}]
        for name in files:
            rel = (Path(root) / name).relative_to(vault).as_posix()
            names.update({rel.casefold(), name.casefold()})
            if name.endswith(".md"):
                names.update({rel.removesuffix(".md").casefold(), name.removesuffix(".md").casefold()})
    return names


def check_page(vault: Path, folder: str, page: wl.Page, targets: set[str], report: Report) -> None:
    where = page.path.relative_to(vault).as_posix()
    kind, fm = wl.FOLDER_TYPE[folder], page.fm
    if not fm:
        report.error(where, "no readable YAML frontmatter")
        return
    if fm.get("type") != kind:
        report.error(where, f"type is {fm.get('type')!r}, expected {kind!r}")
        return
    for key in REQUIRED[kind]:
        value = fm.get(key)
        if value is None or (value in ("", []) and key not in MISSING_OK):
            report.error(where, f"missing frontmatter key `{key}`")
    if wl.TYPE_TAG[kind] not in (fm.get("tags") or []):
        report.error(where, f"tags must include `{wl.TYPE_TAG[kind]}`")
    for key in DATE_KEYS:
        if key in fm and not DATE_RE.match(str(fm[key])):
            report.error(where, f"`{key}` is not YYYY-MM-DD: {fm[key]!r}")
    if kind in ("entity", "concept"):
        count = fm.get("source_count")
        if not isinstance(count, int) or count < 1:
            report.error(where, f"`source_count` must be an integer of 1 or more, got {count!r}")
    if kind == "concept" and fm.get("confidence") not in ("high", "medium", "low"):
        report.error(where, f"`confidence` must be high, medium or low, got {fm.get('confidence')!r}")
    if kind == "source-summary":
        raw = vault / str(fm.get("source_path", ""))
        if not raw.is_file():
            report.error(where, f"raw source not found: {fm.get('source_path')}")
        elif str(fm.get("source_hash")) != wl.sha256_file(raw):
            report.error(
                where,
                f"source_hash does not match the raw file ({wl.sha256_file(raw)}); rerun scaffold-source.py --refresh",
            )
    if wl.PLACEHOLDER in page.text:
        report.error(where, f"`{wl.PLACEHOLDER}` placeholder is still present")
    for target in dict.fromkeys(wl.link_targets(page.text)):
        if target.casefold() not in targets:
            report.error(where, f"broken link [[{target}]]")


def check_index(vault: Path, report: Report) -> None:
    index = vault / "Wiki" / "index.md"
    if not index.is_file():
        report.error("Wiki/index.md", "file not found")
        return
    text = index.read_text(encoding="utf-8")
    for section in wl.INDEX_SECTIONS:
        if f"<!-- BEGIN:{section} -->" not in text or f"<!-- END:{section} -->" not in text:
            report.error("Wiki/index.md", f"missing BEGIN/END markers for `{section}`")
    current, rebuilt = render_index(vault)
    if current != rebuilt:
        report.error("Wiki/index.md", "out of date; run rebuild-index.py")


def check_overview(vault: Path, report: Report) -> None:
    overview = vault / "Wiki" / "overview.md"
    if not overview.is_file():
        report.error("Wiki/overview.md", "file not found")
        return
    text = overview.read_text(encoding="utf-8")
    updated, unmatched = rewrite_overview(text, overview_counts(vault))
    for pattern in unmatched:
        report.error("Wiki/overview.md", f"no line matches {pattern}; update-overview.py cannot keep this count")
    if updated != text:
        report.error("Wiki/overview.md", "counts out of date; run update-overview.py")


def check_log(vault: Path, slugs: list[str], scoped: bool, report: Report) -> None:
    log = vault / "Wiki" / "log.md"
    if not log.is_file():
        report.error("Wiki/log.md", "file not found")
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    missing = [s for s in slugs if not wl.has_log_entry(text, s)]
    if scoped:
        for slug in missing:
            report.error("Wiki/log.md", f"no ingest entry for [[{slug}]]; run log-entry.py")
    elif missing:
        report.warn(
            "Wiki/log.md", f"{len(missing)} source page(s) have no fixed-format ingest entry: {', '.join(missing)}"
        )


def validate(vault: Path, slug: str | None = None, pages_only: bool = False) -> tuple[Report, int]:
    """Validate the wiki, or one ingest when `slug` is given. Return (report, pages checked)."""
    report = Report()
    targets = known_targets(vault)
    checked = 0
    for folder in wl.FOLDER_TYPE:
        for page in wl.pages(vault, folder):
            if slug and page.path.stem != slug and not wl.links_to(page.text, slug):
                continue
            checked += 1
            check_page(vault, folder, page, targets, report)

    sources = wl.pages(vault, "sources")
    seen: dict[str, int] = {}
    for p in sources:
        path = str(p.fm.get("source_path"))
        seen[path] = seen.get(path, 0) + 1
    for path, n in sorted(seen.items()):
        if n > 1:
            report.error("Wiki/sources", f"more than one page names source_path {path}")

    if not pages_only:
        check_index(vault, report)
        check_overview(vault, report)
        check_log(vault, [slug] if slug else [p.path.stem for p in sources], bool(slug), report)
        if slug:
            raw = wl.parse_frontmatter(wl.source_page_path(vault, slug)).get("source_path")
            queue = wl.classify(vault)
            if any(item["source"] == raw for item in queue["new"] + queue["changed"]):
                report.error(str(raw), "still in the check-sources.py queue")
    return report, checked
