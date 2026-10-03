---
name: wiki-ingest
description: "Ingest raw sources into the LLM wiki. Use when the user says /wiki-ingest, 'ingest this', 'process this source', 'add to wiki', or when working in an Obsidian vault with a Wiki/ directory and the user wants to process files from Clippings/ or Twitter-Captures/ into the wiki."
---

# Wiki Ingest

Process raw sources into the wiki. Scripts do the bookkeeping. You write only the source summary, the key claims, and the choice of entities and concepts.

Read the vault's `CLAUDE.md` first. It defines the schema for the vault.

## Scripts

Every script lives in `<skill-dir>/scripts/` and runs directly. Each one finds the vault in this order: `--vault DIR`, then `$CLAUDE_PROJECT_DIR`, then the current directory. Run `<script> --help` for options.

| Script | What it does |
|---|---|
| `check-sources.py` | Lists raw sources that are new or changed, each with its SHA-256. |
| `scaffold-source.py` | Creates `Wiki/sources/<slug>.md` with the slug, frontmatter, `source_hash` and `date_ingested` filled. |
| `wiki-pages.py` | Lists and finds entity and concept pages, creates new ones, and bumps `source_count`. |
| `rebuild-index.py` | Regenerates the `Wiki/index.md` tables. |
| `update-overview.py` | Refreshes the counts in `Wiki/overview.md`. |
| `log-entry.py` | Appends the ingest entry to `Wiki/log.md`. |
| `qmd-refresh.py` | Runs `qmd update && qmd embed`, or skips when `qmd` is not installed. |
| `validate-wiki.py` | Checks schema, links, hashes, index, overview and log. |
| `finalize-ingest.py` | Runs the index, overview, log, search refresh and validation steps in order. |
| `commit-ingest.py` | Commits one source with a fixed message. |
| `backfill-hashes.py` | Adds `source_hash` to old source pages. Run once per old wiki. |

## Workflow

Do steps 1 to 5 once per source. The ingest is done only when step 6 passes.

### 1. Identify sources

If the user names a file, use it. Otherwise run:

```bash
<skill-dir>/scripts/check-sources.py
```

The output lists `new` sources and `changed` sources, each with its path and SHA-256. A changed source was edited after its summary was written. Add `--json` for machine output.

### 2. Scaffold the source page

```bash
<skill-dir>/scripts/scaffold-source.py "<raw path>"
```

For a changed source, add `--refresh`. It updates `source_hash` and `date_ingested` on the existing page. Then read the page and revise the summary to match the new text.

Never edit `source_hash`, `source_path` or `date_ingested` by hand.

### 3. Read the source and write the summary

Read the raw file in full. Never modify it. Replace every `TODO(ingest)` marker on the new page with:

- a summary of two or three factual paragraphs;
- the key claims, one per bullet;
- the entities and concepts the source names, as `[[wikilinks]]`.

Add topic tags to the frontmatter `tags` list. Keep `wiki/source`. Keep the summary factual. Interpretation belongs on concept pages.

### 4. Choose entities and concepts

Check which pages exist. The match uses page names, titles and `aliases`:

```bash
<skill-dir>/scripts/wiki-pages.py list
<skill-dir>/scripts/wiki-pages.py find "Name one" "Name two"
```

For a page that exists, count the new source and add the mention in one command:

```bash
<skill-dir>/scripts/wiki-pages.py bump "<name>" --source <slug> --mention "<what the source says>"
```

For a page that does not exist, create it, then replace its `TODO(ingest)` markers:

```bash
<skill-dir>/scripts/wiki-pages.py new entity "<name>" --kind person --source <slug>
<skill-dir>/scripts/wiki-pages.py new concept "<name>" --confidence medium --source <slug>
```

Entity kinds are `person`, `tool`, `org`, `repo` and `standard`. When the source contradicts a concept page, write the contradiction on that page. Do not overwrite the old claim.

### 5. Finalize

```bash
<skill-dir>/scripts/finalize-ingest.py <slug> --note "<optional free-text line for the log>"
```

The script rejects pages that still hold a `TODO(ingest)` marker, a broken link or a wrong hash. It then rebuilds the index, refreshes the overview counts, appends the log entry, refreshes the search index, and validates the result. Use `--note` for a contradiction, a skipped entity or a vendor caveat.

If the source changes the big picture, edit the themes in `Wiki/overview.md` by hand, then run `update-overview.py`.

### 6. Validate and commit

```bash
<skill-dir>/scripts/validate-wiki.py --source <slug>
<skill-dir>/scripts/commit-ingest.py <slug>
```

`commit-ingest.py` runs the validator first and commits only paths under `Wiki/`. It makes one commit per source and never pushes. Skip it when the user did not ask for commits.

### 7. Report

Tell the user which pages the ingest created and which it updated. Copy them from the log entry.

## Rules

- NEVER modify raw source files.
- NEVER edit the generated tables in `Wiki/index.md` by hand.
- Use `[[wikilinks]]` in all wiki pages.
- Every page has `type:` in frontmatter and a `wiki/*` tag.
- Use `[key::value]` inline metadata for Dataview fields.
- Keep the `<!-- BEGIN:x -->` and `<!-- END:x -->` markers in `Wiki/index.md`.
