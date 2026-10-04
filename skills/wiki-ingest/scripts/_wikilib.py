"""Shared helpers for the wiki-ingest scripts.

This module is imported by the sibling scripts. It is not a command, so it has
no shebang and no executable bit. Each script puts its own directory on
`sys.path`, so `import _wikilib` works from any working directory.

The helpers hold the rules that every script must agree on: which raw files are
sources, how a source hash is computed, how frontmatter is read, how a source
page is found, and how a wikilink is found. Page reads, raw-file hashes and the
source queue are cached for the life of one process, because a command reads
the same files many times and the vault may live on a network drive.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from functools import cache
from pathlib import Path
from typing import NamedTuple

# Raw source folders. Everything below them is a source unless skipped.
RAW_DIRS = ("Clippings", "Twitter-Captures")
# `Twitter-Captures/README.md` holds capture instructions. `bookmarks.md` is a
# backlog of many bookmarks, not one article. Neither is a source.
SKIP_RELATIVE = frozenset({"Twitter-Captures/README.md", "Twitter-Captures/bookmarks.md"})

FOLDER_TYPE = {
    "sources": "source-summary",
    "entities": "entity",
    "concepts": "concept",
    "synthesis": "synthesis",
}
TYPE_TAG = {
    "source-summary": "wiki/source",
    "entity": "wiki/entity",
    "concept": "wiki/concept",
    "synthesis": "wiki/synthesis",
}
INDEX_SECTIONS = ("sources", "entities", "concepts", "synthesis", "unprocessed")
PLACEHOLDER = "TODO(ingest)"
SLUG_LIMIT = 60

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
# A wikilink alias is set off by `|`. Inside a Markdown table it is written `\|`.
ALIAS_SEP_RE = re.compile(r"\\?\|")
FENCED_CODE_RE = re.compile(r"^(?P<fence>```+|~~~+).*?(?:^(?P=fence).*?$|\Z)", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


class Page(NamedTuple):
    path: Path
    fm: dict
    text: str


# --- command line ---------------------------------------------------------------


def make_parser(doc: str | None) -> argparse.ArgumentParser:
    """Return a parser that shows the module docstring and takes `--vault`."""
    parser = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--vault",
        help="vault root (default: $CLAUDE_PROJECT_DIR if it holds Wiki/, else the current directory)",
    )
    return parser


def resolve_vault(arg: str | None) -> Path:
    """Return the vault root, or exit with code 2 if it has no Wiki/ folder."""
    if arg:
        candidates = [Path(arg)]
    else:
        candidates = []
        env = os.environ.get("CLAUDE_PROJECT_DIR")
        if env:
            candidates.append(Path(env))
        candidates.append(Path.cwd())
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "Wiki").is_dir():
            return root
    tried = ", ".join(str(c) for c in candidates)
    sys.exit(f"error: no Wiki/ folder in {tried}. Pass --vault DIR.")


def parse(parser: argparse.ArgumentParser) -> tuple[argparse.Namespace, Path]:
    args = parser.parse_args()
    return args, resolve_vault(args.vault)


# --- small utilities ------------------------------------------------------------


def today() -> str:
    return datetime.date.today().isoformat()


@cache
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(text: str, limit: int | None = SLUG_LIMIT, fallback: str = "untitled") -> str:
    """Return a lowercase ASCII kebab-case slug.

    Accents fold to their base letter. Every other run of characters outside
    `a-z0-9` becomes one hyphen. `limit` cuts at a word boundary; `None` keeps
    the whole slug.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")
    if limit is not None and len(slug) > limit:
        slug = slug[:limit].rsplit("-", 1)[0]
    return slug or fallback


def page_slug(title: str) -> str:
    """Return the file stem for a wiki page title, or "" when the title has no ASCII letter or digit.

    Page slugs are never cut short, so two long titles do not collide by truncation.
    """
    return slugify(title, limit=None, fallback="")


def normalize(name: str) -> str:
    """Fold a page name for matching: case-insensitive, punctuation-insensitive."""
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def quote(value: str) -> str:
    """Return a double-quoted YAML scalar."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def git(vault: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True, check=False)


# --- frontmatter ----------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter text, body) or None when the text has no frontmatter."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def parse_frontmatter_text(text: str) -> dict:
    import yaml  # imported here so the pure helpers load without PyYAML

    split = split_frontmatter(text)
    if split is None:
        return {}
    try:
        data = yaml.safe_load(split[0])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_frontmatter(path: Path) -> dict:
    try:
        return parse_frontmatter_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def first(fm: dict, *keys):
    """Return the first non-empty frontmatter value among keys."""
    for key in keys:
        value = fm.get(key)
        if value not in (None, "", []):
            return value
    return None


def set_frontmatter_value(text: str, key: str, value: str, after: str | None = None) -> str:
    """Set one top-level frontmatter line in place and keep every other byte.

    `value` is written as given, so quote it first if it needs quotes. When the
    key is missing and `after` names a key that exists, the line is added after it.
    """
    split = split_frontmatter(text)
    if split is None:
        raise ValueError("no frontmatter")
    fm_text, body = split
    line = re.compile(rf"(?m)^{re.escape(key)}[ \t]*:.*$")
    if line.search(fm_text):
        fm_text = line.sub(lambda _: f"{key}: {value}", fm_text, count=1)
    else:
        anchor = re.compile(rf"(?m)^([ \t]*){re.escape(after or '')}[ \t]*:.*$")
        if after is None or not anchor.search(fm_text):
            raise ValueError(f"no `{key}` line in frontmatter")
        fm_text = anchor.sub(lambda m: f"{m.group(0)}\n{m.group(1)}{key}: {value}", fm_text, count=1)
    return "---" + fm_text + "---" + body


# --- sources and pages ----------------------------------------------------------


def is_source_path(rel: str) -> bool:
    """Tell whether a vault-relative POSIX path is a raw source."""
    parts = rel.split("/")
    return (
        parts[0] in RAW_DIRS
        and rel.endswith(".md")
        and rel not in SKIP_RELATIVE
        and parts[-1] != "_index.md"
        and "templates" not in parts[:-1]
    )


def raw_sources(vault: Path) -> list[str]:
    """Vault-relative paths of every raw source, sorted."""
    found = []
    for folder in RAW_DIRS:
        base = vault / folder
        if base.is_dir():
            found.extend(p.relative_to(vault).as_posix() for p in base.rglob("*.md"))
    return sorted(rel for rel in found if is_source_path(rel))


@cache
def pages(vault: Path, folder: str) -> tuple[Page, ...]:
    """Every page in `Wiki/<folder>/`, read once per process. Do not call after writing a page."""
    directory = vault / "Wiki" / folder
    if not directory.is_dir():
        return ()
    out = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        out.append(Page(path, parse_frontmatter_text(text), text))
    return tuple(out)


def source_page_path(vault: Path, slug: str) -> Path:
    return vault / "Wiki" / "sources" / f"{slug}.md"


def source_pages(vault: Path) -> dict[str, Page]:
    """Map source_path to the source page that names it."""
    return {str(p.fm["source_path"]): p for p in pages(vault, "sources") if p.fm.get("source_path")}


def resolve_slug(vault: Path, arg: str) -> str:
    """Turn a source page name or a raw path into a source page name, or exit with code 2."""
    if source_page_path(vault, arg).is_file():
        return arg
    page = source_pages(vault).get(arg)
    if page is None:
        sys.exit(f"error: no source page for {arg}; run scaffold-source.py first")
    return page.path.stem


@cache
def classify(vault: Path) -> dict:
    """Bucket every raw source as new or changed, and count the unchanged ones.

    The rule matches the retired `vault-status.sh`: a raw file is new when no
    source page names it in `source_path`, and changed when the page's
    `source_hash` differs from the file's SHA-256. A page with no hash counts as
    changed so a backfill is visible.
    """
    indexed = source_pages(vault)
    new, changed, unchanged = [], [], 0
    for rel in raw_sources(vault):
        digest = sha256_file(vault / rel)
        page = indexed.get(rel)
        if page is None:
            new.append({"source": rel, "sha256": digest})
            continue
        recorded = page.fm.get("source_hash")
        if not recorded:
            reason = "no source_hash recorded (needs backfill)"
        elif str(recorded) != digest:
            reason = "content hash changed since ingest"
        else:
            unchanged += 1
            continue
        changed.append({"source": rel, "sha256": digest, "page": page.path.stem, "reason": reason})
    return {"new": new, "changed": changed, "unchanged_count": unchanged}


# --- links and the log ----------------------------------------------------------


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans. Obsidian shows links in code as text."""
    return INLINE_CODE_RE.sub("", FENCED_CODE_RE.sub("", text))


def wikilink_target(inner: str) -> str:
    """Return the page name in the inside of a wikilink, without alias or heading."""
    return ALIAS_SEP_RE.split(inner, maxsplit=1)[0].split("#")[0].strip()


def wikilink(target: str, title: str | None = None, table: bool = False) -> str:
    """Write `[[target|title]]`, or `[[target]]` when the title adds nothing.

    In a Markdown table the separator is `\\|`, so the pipe does not end the cell.
    """
    title = re.sub(r"[\[\]|]", "", title or "").strip()
    if not title or title == target:
        return f"[[{target}]]"
    return f"[[{target}{chr(92) + '|' if table else '|'}{title}]]"


def page_title(page: Page) -> str:
    return str(page.fm.get("title") or page.path.stem)


def page_link(page: Page, table: bool = False) -> str:
    """Link to a wiki page by file stem and show its title."""
    return wikilink(page.path.stem, page_title(page), table)


def link_targets(text: str) -> list[str]:
    targets = (wikilink_target(m.group(1)) for m in WIKILINK_RE.finditer(strip_code(text)))
    return [t for t in targets if t]


def links_to(text: str, name: str) -> bool:
    if name.casefold() not in text.casefold():
        return False
    return any(t.casefold() == name.casefold() for t in link_targets(text))


def log_marker(slug: str) -> str:
    """The line that proves an ingest entry exists for a source."""
    return f"- Created: [[{slug}]] (source)"


def has_log_entry(log_text: str, slug: str) -> bool:
    return log_marker(slug) in log_text


def ingest_summary(vault: Path, slug: str, date: str) -> dict:
    """List entity and concept pages that link to a source page, split by created or updated.

    Each list holds `Page` objects.

    A page counts as created when its `date_created` equals `date`. The result
    is deterministic, so the log entry and the commit message agree.
    """
    out = {}
    for folder in ("entities", "concepts"):
        out[folder] = {"created": [], "updated": []}
        for page in pages(vault, folder):
            if links_to(page.text, slug):
                kind = "created" if str(page.fm.get("date_created")) == date else "updated"
                out[folder][kind].append(page)
    return out
