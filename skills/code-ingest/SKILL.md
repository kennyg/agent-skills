---
name: code-ingest
description: "Ingest a codegraph-indexed codebase into a repo-local code wiki. Use when the user says /code-ingest, 'ingest this codebase', 'document this repo', 'build a code wiki', or when working in a repo with a .codegraph/ index (or one that can be indexed) and the user wants code turned into wiki pages. Creates Wiki/ if absent."
---

# Code Ingest

Turn a codebase into a navigable wiki, grounded in the [codegraph](https://github.com/colbymchenry/codegraph) index rather than re-reading every file by hand. Same page taxonomy as `wiki-ingest` (sources → entities → concepts), but the raw sources are code files and the facts come from codegraph's symbol/edge graph.

The wiki lives **repo-local** at `<repo>/Wiki/`, next to the code it documents — not in a personal knowledge vault. Read the repo's CLAUDE.md for project-specific conventions first.

## Prerequisites

The repo must be indexed. codegraph takes the project path as a **positional
argument** — there is no `-p` flag.

```bash
codegraph status "$REPO"              # confirms .codegraph/codegraph.db exists
codegraph init --index "$REPO"        # first time: creates .codegraph/ AND indexes
codegraph index "$REPO"               # re-index an already-initialized repo
codegraph sync "$REPO"                # cheaper incremental update
```

`index` refuses to run before `init` ("CodeGraph not initialized"), so a repo
that has never been indexed needs `init --index`, not `index`. Scope comes from
the repo's `.gitignore`, which codegraph honors — check `status` output before
ingesting if the repo vendors dependencies or build artifacts that aren't
ignored.

All facts below come from `<repo>/.codegraph/codegraph.db` (SQLite). Key tables: `files(path, content_hash, language)`, `nodes(kind, name, qualified_name, file_path, signature, ...)`, `edges(source, target, kind)`.

## Workflow

### 1. Identify sources

Ask the checker what is new or changed since the last ingest:

```bash
uv run <skill-dir>/scripts/check-sources.py "$REPO" --mode code
```

`--mode code` reads the codegraph `files` table and compares each file's `content_hash` against the `source_hash` recorded on its `Wiki/sources/` page. It reports `new` (never ingested) and `changed` (refactored since ingest).

`Wiki/` is excluded automatically. codegraph indexes whatever is in the repo, and after step 8 that includes `Wiki/code-areas.yml`, which this skill generates — without the exclusion the pipeline feeds on its own output.

Everything else codegraph indexed is fair game, so **scope deliberately**. A full index may list 100+ files and will include lockfiles, fixtures, and generated code that deserve no page. Ingest `src/**` before tests and scripts, and pass the same globs to `scaffold-sources.py`:

```bash
uv run <skill-dir>/scripts/scaffold-sources.py "$REPO" --only 'src/**' --only 'vite.config.ts'
```

Files you deliberately skip stay in the checker's `new` list. That is correct — it is a standing reminder of what the wiki does not cover. Record the decision in `Wiki/log.md` so the next run doesn't re-litigate it.

### 2. Read each source, grounded in the graph

Read the file with the Read tool. You need it for the prose slots in step 3 —
what the file is *for*, and what its comments say that the graph cannot.

Do not hand-write SQL to pull symbols and edges. `scaffold-sources.py` issues
those queries in step 3 and owns the answers: which node kinds count, whether
call-site multiplicity is collapsed, how long a signature may be. Duplicating
them here would create a second definition that drifts from the first.

Ad-hoc queries are still fine for *investigating* something specific — the
schema is `files(path, content_hash, language)`,
`nodes(kind, name, qualified_name, file_path, signature, ...)`,
`edges(source, target, kind)`. Just don't transcribe the results onto a page;
regenerate the page instead.

Two blind spots to check for rather than assume away. Anonymous callbacks are
not extracted — a test file of `describe`/`it` bodies, or a config that is one
arrow function passed to `defineConfig`, yields **zero** named symbols and can
ground no entity. And `await import(...)` produces no `imports` edge, so
dynamically-coupled files look unrelated in the graph. Both cases still deserve
a source page; say in it that the graph is empty and why.

Never modify source code. This skill only reads.

### 3. Scaffold source pages, then write only the prose

Do **not** hand-write source pages. Generate them:

```bash
uv run <skill-dir>/scripts/scaffold-sources.py "$REPO" --dry-run    # review first
uv run <skill-dir>/scripts/scaffold-sources.py "$REPO"
uv run <skill-dir>/scripts/scaffold-sources.py "$REPO" --only 'src/**'  # scope a big repo
```

One page per indexed file at `Wiki/sources/<slug>.md`. The script owns
everything the graph already knows and writes it into fenced blocks:

| Section | Fence | Source |
|---|---|---|
| frontmatter | — | `files.path`, `content_hash`, `language` |
| Key Symbols | `<!-- BEGIN:symbols -->` | `nodes` |
| Depends On | `<!-- BEGIN:depends -->` | outbound `calls` + `imports` edges |
| Used By | `<!-- BEGIN:usedby -->` | inbound `calls` edges |

**Your job is the two prose slots**, `## Purpose` and `## Notes`, marked with
`_TODO —_` placeholders. Everything outside a fence survives regeneration, so
prose written once is never clobbered; re-running refreshes only the tables and
the `source_hash`. Frontmatter keys the script does not own — `title`, extra
area tags — are preserved too.

Write Purpose in 2–3 sentences: what the file is for and why it exists. Write
Notes for what the graph *cannot* say — gotchas, contradictions, dead code, the
comment that explains an upstream API quirk. Do not restate the symbol table in
prose; it is already on the page and it is already correct.

Same inputs produce byte-identical output, so a page diff after re-ingest shows
real code movement rather than rephrasing.

### 4. Create or update entity pages

Code entities are the durable named things: modules, classes, interfaces, and the load-bearing functions. Check if `Wiki/entities/<name>.md` exists.
- **New**: `type: entity`, `entity_kind:` (module/class/interface/function/type), `source_count: 1`, and `realized_by:` — the list of codegraph `qualified_name`s that ground this entity in real symbols.
- **Existing**: add facts, extend `realized_by`, bump `source_count`, update `date_updated`.

```yaml
---
type: entity
title: "Svelte framework resolver"
entity_kind: module
source_count: 1
realized_by:
  - "getSvelteKitRouteInfo"
  - "filePathToSvelteKitRoute"
date_created: <today>
date_updated: <today>
tags: [wiki/entity]
---
```

`realized_by` is what makes the code wiki auditable: every entity points back at symbols that actually exist in the graph. `rebuild-index.py` surfaces its length as the **Symbols** column.

### 5. Create or update concept pages

Concepts are the architecture the code embodies — subsystems, patterns, data flows (e.g. "Extraction pipeline", "Reference resolution", "MCP transport"). Check if `Wiki/concepts/<name>.md` exists.
- **New**: `type: concept`, `confidence:` (high/medium/low), `source_count: 1`, `realized_by:` (grounding symbols/files).
- **Existing**: add insight, update relationships, bump `source_count`, update `date_updated`.

When the code contradicts a documented concept (dead code, a pattern half-migrated), note it explicitly on the concept page rather than silently trusting either side.

### 6. Verify grounding

Before rebuilding the index, prove every page is anchored in real code:

```bash
uv run <skill-dir>/scripts/verify-grounding.py "$REPO"
```

Two checks run. First, every `realized_by` entry is resolved against the index.
Three outcomes:

- **missing** — the symbol is not in the index. Either invented, mistyped, or
  the code was renamed after ingest. Fix the page, or re-index and re-check.
- **grounded by file, not symbol** — legal, and the honest fallback for files
  the extractor could not name, but prefer symbols. `--strict` makes it fail.
- **no `realized_by` at all** — an ungrounded page, which the code wiki should
  not contain. Fails by default; `--allow-ungrounded` downgrades it to a report.

Second, every `` `path/to/file.ext:123` `` citation in prose is checked: unknown
file, line past EOF, or **stale anchor** — an identifier named in the same
paragraph that really exists in that file, at a different line. Anchors resolve
against the index first and the source text second, so calls into dependencies
(which codegraph does not record) are checked too.

That last one is the reason this check exists. A rename breaks `realized_by`
loudly, but inserting lines above a function shifts every citation below it
silently: each still resolves, still lands in the file, just no longer at what
the sentence says. Prefer naming the symbol over citing a line — `` `stopSession` ``
survives a refactor that `src/main.ts:186` does not. `--no-line-refs` skips this
check.

Do not proceed to step 7 with a failing run. An unverified `realized_by` is
worse than none: the **Symbols** column in `index.md` will report a count that
looks like evidence.

### 7. Rebuild the index

Do **not** hand-edit `Wiki/index.md`. Regenerate it from page frontmatter, feeding in the checker's unprocessed list:

```bash
uv run <skill-dir>/scripts/check-sources.py "$REPO" --mode code --json > /tmp/code-sources.json
uv run <skill-dir>/scripts/rebuild-index.py "$REPO" --unprocessed /tmp/code-sources.json
```

Prose you write outside the `<!-- BEGIN:x -->` / `<!-- END:x -->` fences is preserved; only the tables regenerate.

### 8. Refresh the area map

Regenerate `Wiki/code-areas.yml` — the coarse map of the codebase — from the graph, not by hand:

```bash
uv run <skill-dir>/scripts/seed-areas.py "$REPO" --dry-run   # review first
uv run <skill-dir>/scripts/seed-areas.py "$REPO"             # write it
```

Areas come from framework **route** nodes when the repo has them (web apps); otherwise the seeder falls back to module boundaries derived from the graph. Always review `--dry-run` before writing.

`key_symbols` lists only `is_exported=1` symbols, so module-private classes are
absent by design — an empty `key_symbols` means the area exports nothing named,
not that the seeder failed.

### 9. Update log

Append to `Wiki/log.md`:

```markdown
## [YYYY-MM-DD] code-ingest | <path or area>

- Source: [[<source-slug>]] (hash <short>)
- Created entities: [[Entity1]], [[Entity2]]
- Updated concepts: [[Concept1]]
```

### 10. Report

Tell the user what was created/updated and which sources remain unprocessed.

## Rules

- NEVER modify source code — this skill only reads the repo and writes under `Wiki/`.
- Ground every entity/concept in `realized_by` symbols that exist in the codegraph index; don't invent structure the graph doesn't support. Prove it with `verify-grounding.py` before generating the index — a `realized_by` nobody checked is decoration.
- Record `source_hash` on every source page (the file's `content_hash`) so re-ingest is change-driven, not blind.
- Generate what the graph knows; write only what it doesn't. Source pages come from `scaffold-sources.py`; `index.md` and `code-areas.yml` from their scripts. Never hand-maintain a generated block — edits inside `<!-- BEGIN:x -->` fences are overwritten on the next run.
- Use `[[wikilinks]]` heavily; every page gets `type:` and `wiki/*` tags.
- Re-run `codegraph index` (or `codegraph sync`) before ingest if the working tree has moved since the last index.
