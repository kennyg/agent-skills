---
name: code-ingest
description: "Ingest a codegraph-indexed codebase into a repo-local code wiki. Use when the user says /code-ingest, 'ingest this codebase', 'document this repo', 'build a code wiki', or when working in a repo that has a .codegraph/ index and a Wiki/ directory and the user wants code turned into wiki pages."
---

# Code Ingest

Turn a codebase into a navigable wiki, grounded in the [codegraph](https://github.com/) index rather than re-reading every file by hand. Same page taxonomy as `wiki-ingest` (sources → entities → concepts), but the raw sources are code files and the facts come from codegraph's symbol/edge graph.

The wiki lives **repo-local** at `<repo>/Wiki/`, next to the code it documents — not in a personal knowledge vault. Read the repo's CLAUDE.md for project-specific conventions first.

## Prerequisites

The repo must be indexed. Check, and index if needed:

```bash
codegraph -p "$REPO" status   # confirms .codegraph/codegraph.db exists
codegraph -p "$REPO" index    # (re)build the index if missing or stale
```

All facts below come from `<repo>/.codegraph/codegraph.db` (SQLite). Key tables: `files(path, content_hash, language)`, `nodes(kind, name, qualified_name, file_path, signature, ...)`, `edges(source, target, kind)`.

## Workflow

### 1. Identify sources

Ask the checker what is new or changed since the last ingest:

```bash
uv run <skill-dir>/scripts/check-sources.py "$REPO" --mode code
```

`--mode code` reads the codegraph `files` table and compares each file's `content_hash` against the `source_hash` recorded on its `Wiki/sources/` page. It reports `new` (never ingested) and `changed` (refactored since ingest). Scope large repos: ingest `src/**` before tests and scripts; a full index may list 100+ files.

### 2. Read each source, grounded in the graph

Read the file with the Read tool, then pull its symbols and relationships from the index instead of inferring them:

```bash
DB="$REPO/.codegraph/codegraph.db"
# Symbols defined in this file
sqlite3 -header "$DB" "SELECT kind, name, signature, start_line FROM nodes
  WHERE file_path='<path>' AND kind IN ('function','method','class','interface','type_alias') ORDER BY start_line;"
# What this file's symbols call, and who calls into them
sqlite3 "$DB" "SELECT s.name AS caller, t.name AS callee FROM edges e
  JOIN nodes s ON e.source=s.id JOIN nodes t ON e.target=t.id
  WHERE e.kind='calls' AND s.file_path='<path>';"
```

Never modify source code. This skill only reads.

### 3. Create source summary

Write to `Wiki/sources/<slug>.md`, one page per code file. Record the exact `content_hash` codegraph holds so the checker can detect drift:

```yaml
---
type: source-summary
title: "<path or a human label>"
source_kind: file
source_path: "<repo-relative path>"      # e.g. src/resolution/frameworks/svelte.ts
source_hash: "<files.content_hash for that path>"
language: "<files.language>"
date_ingested: <today>
tags:
  - wiki/source
  - <area tags>
---
```

Get `source_hash` with: `sqlite3 "$DB" "SELECT content_hash FROM files WHERE path='<path>';"`

Include: Purpose (2–3 sentences), Key Symbols (as `[[wikilinks]]` to entities), Depends On / Used By (from `calls`/`imports` edges), Raw Source link.

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

### 6. Rebuild the index

Do **not** hand-edit `Wiki/index.md`. Regenerate it from page frontmatter, feeding in the checker's unprocessed list:

```bash
uv run <skill-dir>/scripts/check-sources.py "$REPO" --mode code --json > /tmp/code-sources.json
uv run <skill-dir>/scripts/rebuild-index.py "$REPO" --unprocessed /tmp/code-sources.json
```

Prose you write outside the `<!-- BEGIN:x -->` / `<!-- END:x -->` fences is preserved; only the tables regenerate.

### 7. Refresh the area map

Regenerate `Wiki/code-areas.yml` — the coarse map of the codebase — from the graph, not by hand:

```bash
uv run <skill-dir>/scripts/seed-areas.py "$REPO" --dry-run   # review first
uv run <skill-dir>/scripts/seed-areas.py "$REPO"             # write it
```

Areas come from framework **route** nodes when the repo has them (web apps); otherwise the seeder falls back to module boundaries derived from the graph. Always review `--dry-run` before writing.

### 8. Update log

Append to `Wiki/log.md`:

```markdown
## [YYYY-MM-DD] code-ingest | <path or area>

- Source: [[<source-slug>]] (hash <short>)
- Created entities: [[Entity1]], [[Entity2]]
- Updated concepts: [[Concept1]]
```

### 9. Report

Tell the user what was created/updated and which sources remain unprocessed.

## Rules

- NEVER modify source code — this skill only reads the repo and writes under `Wiki/`.
- Ground every entity/concept in `realized_by` symbols that exist in the codegraph index; don't invent structure the graph doesn't support.
- Record `source_hash` on every source page (the file's `content_hash`) so re-ingest is change-driven, not blind.
- Regenerate `index.md` and `code-areas.yml` with the scripts; never hand-maintain them.
- Use `[[wikilinks]]` heavily; every page gets `type:` and `wiki/*` tags.
- Re-run `codegraph index` (or `codegraph sync`) before ingest if the working tree has moved since the last index.
