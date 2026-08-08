---
name: wiki-ingest
description: "Ingest raw sources into the LLM wiki. Use when the user says /wiki-ingest, 'ingest this', 'process this source', 'add to wiki', or when working in an Obsidian vault with a Wiki/ directory and the user wants to process files from Clippings/ or Twitter-Captures/ into the wiki."
---

# Wiki Ingest

Process one or more raw sources into the wiki following the LLM wiki pattern. Read CLAUDE.md for vault-specific conventions first.

## Workflow

### 1. Identify sources

If the user specifies a file, use that. Otherwise run the shared checker in files mode:

```bash
uv run <skill-dir>/scripts/check-sources.py "$CLAUDE_PROJECT_DIR" --mode files
```

This hashes each raw clipping (sha256) and compares it against the `source_hash` recorded on its `Wiki/sources/` page. It reports both **new** files (never ingested) and **changed** files (edited since ingest) — so a re-clipped or corrected source resurfaces instead of going stale. Add `--json` to feed the index rebuild in step 6.

### 2. Read each source fully

Use the Read tool or `obsidian read` CLI. Never modify raw source files.

### 3. Create source summary

Write to `Wiki/sources/<slug>.md`:

```yaml
---
type: source-summary
title: "<title>"
source_path: "<path from vault root>"
source_hash: "<sha256 of the raw file>"
source_url: "<url>"
author: "<author>"
date_ingested: <today>
tags:
  - wiki/source
  - <topic tags>
---
```

Get `source_hash` with `shasum -a 256 "<raw file>"` (or `python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "<raw file>"`). It must match what `check-sources.py --mode files` computes, so the checker recognises this source as unchanged on the next run.

Include: Summary (2-3 paragraphs), Key Claims, Entities Mentioned (as `[[wikilinks]]`), Concepts Touched (as `[[wikilinks]]`), Raw Source link.

### 4. Create or update entity pages

For each entity mentioned, check if `Wiki/entities/<name>.md` exists.
- **New**: Create with `type: entity`, `entity_kind:` (person/tool/org/repo), `source_count: 1`
- **Existing**: Add mention, update facts, bump `source_count`, update `date_updated`

### 5. Create or update concept pages

For each concept, check if `Wiki/concepts/<name>.md` exists.
- **New**: Create with `type: concept`, `confidence:` (high/medium/low), `source_count: 1`
- **Existing**: Add insight, update relationships, bump `source_count`, update `date_updated`

### 6. Rebuild index

Do **not** hand-edit `Wiki/index.md`. Regenerate it from page frontmatter, feeding in the checker's unprocessed list:

```bash
uv run <skill-dir>/scripts/check-sources.py "$CLAUDE_PROJECT_DIR" --mode files --json > /tmp/wiki-sources.json
uv run <skill-dir>/scripts/rebuild-index.py "$CLAUDE_PROJECT_DIR" --unprocessed /tmp/wiki-sources.json
```

Prose outside the `<!-- BEGIN:x -->` / `<!-- END:x -->` fences is preserved; the Sources/Entities/Concepts/Synthesis/Unprocessed tables regenerate deterministically. On the first run against a legacy hand-maintained index, the old headings and tables are migrated in place (no duplication).

### 7. Update overview

Edit `Wiki/overview.md` if the source materially changes the big picture. Update the Status counts.

### 8. Update log

Append to `Wiki/log.md`:

```markdown
## [YYYY-MM-DD] ingest | <Source Title>

- Source: [[<raw source path>]]
- Created: [[<source-slug>]] (source)
- Created entities: [[entity1]], [[entity2]]
- Updated entities: [[entity3]]
- Created concepts: [[concept1]]
- Updated concepts: [[concept2]]
```

### 9. Refresh search index

```bash
qmd update && qmd embed
```

### 10. Report

Tell the user what was created/updated.

## Rules

- NEVER modify raw source files
- Use `[[wikilinks]]` heavily in all wiki pages
- Every page gets `type:` in frontmatter and `wiki/*` tags
- Keep summaries factual; interpretation goes in concept/synthesis pages
- When sources contradict existing wiki content, note explicitly on the concept page
- Use `[key::value]` inline metadata for Dataview fields
