---
name: wiki-ingest
description: "Ingest raw sources into the LLM wiki. Use when the user says /wiki-ingest, 'ingest this', 'process this source', 'add to wiki', or when working in an Obsidian vault with a Wiki/ directory and the user wants to process files from Clippings/ or Twitter-Captures/ into the wiki."
---

# Wiki Ingest

Process one or more raw sources into the wiki following the LLM wiki pattern. Read CLAUDE.md for vault-specific conventions first.

## Workflow

### 1. Identify sources

If the user specifies a file, use that. Otherwise run the check script:

```bash
uv run /path/to/skill/scripts/check-sources.py "$CLAUDE_PROJECT_DIR"
```

This compares raw source files against Wiki/sources/ and lists any new unprocessed files.

### 2. Read each source fully

Use the Read tool or `obsidian read` CLI. Never modify raw source files.

### 3. Create source summary

Write to `Wiki/sources/<slug>.md`:

```yaml
---
type: source-summary
title: "<title>"
source_path: "<path from vault root>"
source_url: "<url>"
author: "<author>"
date_ingested: <today>
tags:
  - wiki/source
  - <topic tags>
---
```

Include: Summary (2-3 paragraphs), Key Claims, Entities Mentioned (as `[[wikilinks]]`), Concepts Touched (as `[[wikilinks]]`), Raw Source link.

### 4. Create or update entity pages

For each entity mentioned, check if `Wiki/entities/<name>.md` exists.
- **New**: Create with `type: entity`, `entity_kind:` (person/tool/org/repo), `source_count: 1`
- **Existing**: Add mention, update facts, bump `source_count`, update `date_updated`

### 5. Create or update concept pages

For each concept, check if `Wiki/concepts/<name>.md` exists.
- **New**: Create with `type: concept`, `confidence:` (high/medium/low), `source_count: 1`
- **Existing**: Add insight, update relationships, bump `source_count`, update `date_updated`

### 6. Update index

Edit `Wiki/index.md`: add source to Sources table, add/update entities and concepts tables, remove source from Unprocessed.

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
