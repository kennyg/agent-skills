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
| `scaffold-source.py` | Renames the clipping to its slug, then creates `Wiki/sources/<slug>.md` with the slug, frontmatter, `source_hash` and `date_ingested` filled. |
| `wiki-pages.py` | Lists and finds entity and concept pages, creates new ones with a slug file name, and bumps `source_count`. |
| `rebuild-index.py` | Regenerates the `Wiki/index.md` tables. |
| `update-overview.py` | Refreshes the counts in `Wiki/overview.md`. |
| `log-entry.py` | Appends the ingest entry to `Wiki/log.md`. |
| `qmd-refresh.py` | Runs `qmd update && qmd embed`, or skips when `qmd` is not installed. |
| `validate-wiki.py` | Checks schema, links, hashes, index, overview and log. |
| `finalize-ingest.py` | Runs the index, overview, log, search refresh and validation steps in order. |
| `commit-ingest.py` | Commits one source with a fixed message. |
| `backfill-hashes.py` | Adds `source_hash` to old source pages. Run once per old wiki. |
| `migrate-slugs.py` | Renames wiki pages with a space in the file name to slugs and rewrites the links to them. Run once per old wiki. |
| `slug-clippings.py` | Renames clippings that are not slugs, sets `source_path` on their source pages, and rewrites the links to them. Run once per old wiki. |

## Page names

Every wiki page file name is a slug. It has no spaces.

- The file name is the lowercase kebab-case slug of the page title. It uses ASCII only. Punctuation is dropped. A run of separators becomes one hyphen. `MCP (Model Context Protocol)` is `mcp-model-context-protocol.md`. `Exploration-Exploitation Trade-off` is `exploration-exploitation-trade-off.md`.
- The frontmatter keeps the title in `title:` and lists it in `aliases:`. Search and link suggestions in Obsidian find the page by title.
- Write a link as `[[slug|Title]]`. In a Markdown table, write `[[slug\|Title]]`. A link to an alias does not open the page, so always link the slug.
- One file name belongs to one page. `wiki-pages.py new` stops when a page in `Wiki/` already uses the slug. Pass `--slug` to pick another one.
- `Wiki/index.md`, the overview and the log use the same link form. The scripts write it.

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

For a clipping in `Clippings/`, the script first renames the file to the slug of its name with `git mv`. `Post by @karpathy on X.md` becomes `post-by-karpathy-on-x.md`. The content and the `source_hash` do not change, and the script stops if the hash differs after the move. `source_path` and the `Raw Source` link use the new name. The script refuses when a note in `Clippings/` already has the new name. Pass `--clip-slug <name>` to choose another name. The script warns when a note in another folder has the same name, for example the source page it creates.

`Twitter-Captures/` files already have slug names. The script never renames them.

For a changed source, add `--refresh`. It updates `source_hash` and `date_ingested` on the existing page. Then read the page and revise the summary to match the new text.

Never edit `source_hash`, `source_path` or `date_ingested` by hand.

### 3. Read the source and write the summary

Read the raw file in full. Never modify it. Replace every `TODO(ingest)` marker on the new page with:

- a summary of two or three factual paragraphs;
- the key claims, one per bullet;
- the entities and concepts the source names, as `[[slug|Title]]` wikilinks. Get each slug from `wiki-pages.py find`.

Add topic tags to the frontmatter `tags` list. Keep `wiki/source`. Keep the summary factual. Interpretation belongs on concept pages.

### 4. Choose entities and concepts

Check which pages exist. The match uses slugs, titles and `aliases`. For a page that exists, `find` prints the link to use:

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

`new` writes `Wiki/<folder>/<slug>.md` with `title` and `aliases` set. Use `--alias` for other names the page goes by. Entity kinds are `person`, `tool`, `org`, `repo` and `standard`. When the source contradicts a concept page, write the contradiction on that page. Do not overwrite the old claim.

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

`commit-ingest.py` runs the validator first and commits only paths under `Wiki/` and the raw source. The raw source is in the commit only to record the rename from `git mv`. It makes one commit per source and never pushes. Skip it when the user did not ask for commits.

### 7. Report

Tell the user which pages the ingest created and which it updated. Copy them from the log entry.

## Rules

- NEVER edit the content of raw source files. The only change allowed is the rename of a clipping to its slug, which `scaffold-source.py` and `slug-clippings.py` make with `git mv`.
- NEVER edit the generated tables in `Wiki/index.md` by hand.
- Use `[[slug|Title]]` wikilinks in all wiki pages. Never create a wiki page file name with a space.
- Every page has `type:` in frontmatter and a `wiki/*` tag.
- Use `[key::value]` inline metadata for Dataview fields.
- Keep the `<!-- BEGIN:x -->` and `<!-- END:x -->` markers in `Wiki/index.md`.

## Migrate old page names

An older wiki has pages with a space in the file name, such as `Wiki/concepts/Understanding LLM Output.md`. `validate-wiki.py` reports each one as an error. Run the migration once, on a clean git tree:

```bash
<skill-dir>/scripts/migrate-slugs.py --dry-run
<skill-dir>/scripts/migrate-slugs.py
```

The dry run prints the rename map, the link count per file, and any collision. It writes nothing.

The real run does five things:

1. Renames each page with `git mv`.
2. Adds `title` and `aliases` where they are missing. `aliases` also lists the old file name.
3. Rewrites each link to a renamed page in `Wiki/`, `Ideas/` and `Inbox/` as `[[slug|Title]]`. A link keeps its display text and its `#heading` or `^block` suffix. An embed keeps its own form. Links in code stay as they are.
4. Rebuilds the tables in `Wiki/index.md`.
5. Appends an entry to `Wiki/log.md`.

The script never writes `Clippings/` or `Twitter-Captures/`. A link there to a renamed page stops opening, because Obsidian does not resolve a link through `aliases`. The dry run lists these links.

The script stops with exit code 1 when two titles give one slug, or when a slug matches the name of another note. Pass `--slug "Old file name=new-slug"` once per page to choose a different slug. Run `validate-wiki.py` after the migration, then commit.

## Migrate old clipping names

The Obsidian Web Clipper names a clipping after the page title, such as `Clippings/Post by @karpathy on X.md`. New ingests rename the clipping to a slug. Clippings ingested earlier keep their old names until you run the backfill. `validate-wiki.py` warns about each one. Run it once, on a clean git tree:

```bash
<skill-dir>/scripts/slug-clippings.py --dry-run
<skill-dir>/scripts/slug-clippings.py
```

The dry run prints the rename map, the source pages it changes, the link count per file, every name clash and every collision. It writes nothing.

The real run does five things:

1. Renames each clipping whose name is not a slug with `git mv`, and checks that its SHA-256 is the same afterwards. If one hash differs, it moves every file back and stops.
2. Sets `source_path` on each source page that names a renamed clipping.
3. Rewrites each link to an old clipping name in `Wiki/`, `Ideas/` and `Inbox/` to `[[Clippings/slug|Old name]]`. A link keeps its display text and its `#heading` or `^block` suffix. Links in code stay as they are.
4. Rebuilds the tables in `Wiki/index.md`.
5. Appends an entry to `Wiki/log.md`.

The script never edits the content of a clipping, and it never writes `Twitter-Captures/`. A link to an old name inside a clipping stays as it is. The dry run lists these links.

The script stops with exit code 1 on a collision. A collision is two clippings with one slug, or a note in `Clippings/` that has the slug. Pass `--clip-slug "Old file name=new-slug"` once per clipping to choose another name. A clash is only a warning. It means a note in another folder has the same name, such as `Wiki/sources/live-music-archive.md`. Links to the clipping use the folder path, so they still resolve.

If someone renames a clipping by hand, `check-sources.py` lists it as `renamed`, not `new`. `validate-wiki.py` then reports the source page with the missing raw file and names the new path. Set `source_path` and the `Raw Source` link on that page to the new path.
