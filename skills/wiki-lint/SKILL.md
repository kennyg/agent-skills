---
name: wiki-lint
description: "Health-check the LLM wiki for quality issues. Use when the user says /wiki-lint, 'lint the wiki', 'health check', 'check the wiki', or wants to find broken links, orphan pages, stale content, or missing cross-references in the Wiki/ directory."
---

# Wiki Lint

Run a health check on the wiki and report findings. Read CLAUDE.md for vault-specific conventions first.

## Workflow

### 1. Run the lint script

```bash
uv run <skill-dir>/scripts/lint-wiki.py "$CLAUDE_PROJECT_DIR"
```

This scans all wiki pages and reports broken wikilinks, orphan pages, index drift, missing pages (referenced 2+ times), and unprocessed sources.

### 2. Review the output

The script groups findings by severity. Read the output and plan fixes.

### 3. Check for issues

**Broken wikilinks** — links to pages that don't exist in the wiki.

**Orphan pages** — wiki pages with no inbound links from other wiki pages.

**Stale pages** — `date_updated` significantly older than newer sources touching the same entities/concepts.

**Missing pages** — entities or concepts referenced in `[[wikilinks]]` across multiple pages but lacking their own dedicated page.

**Low source counts** — entity pages with `source_count: 1` that might be too granular and could merge.

**Missing cross-references** — related concepts/entities that don't link to each other.

**Contradictions** — claims on one page that conflict with claims on another.

**Index drift** — pages that exist on disk but are missing from `Wiki/index.md`, or index entries pointing to files that don't exist.

**Unprocessed sources** — raw sources in `Clippings/` or `Twitter-Captures/` not yet ingested.

### 4. Report findings

Present findings grouped by severity:
- **Errors** — broken links, index drift (fix immediately)
- **Warnings** — orphans, stale pages, missing pages (recommend fixes)
- **Info** — low source counts, potential merges, new questions to investigate

### 5. Fix with permission

Offer to fix errors and warnings. Ask before making large changes. For missing pages, offer to create stubs.

### 6. Log the lint

Append to `Wiki/log.md`:

```markdown
## [YYYY-MM-DD] lint | Health check

- Broken links found: N (fixed: N)
- Orphan pages: N
- Stale pages: N
- Missing pages: N (created stubs: N)
- Index drift: N (fixed: N)
- Unprocessed sources: N
```

### 7. Refresh search index

```bash
qmd update && qmd embed
```
