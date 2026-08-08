# Changelog

## v1.3.0 (2026-08-08)

Added a code wiki skill and a runbook skill for landing a first mate and its fleet on a remote host.

### New Skills

- **code-ingest** — Turn a codegraph-indexed codebase into a repo-local `Wiki/`. Same sources → entities → concepts taxonomy as wiki-ingest, but grounded in codegraph's symbol/edge graph rather than re-reading every file.
- **going-ashore** — Runbook for standing up a first mate and its fleet on a remote host over SSH + herdr; covers survey, provision, raise-the-flag, land, boot, and bridge.

### code-ingest Details

- **Deterministic page generation** — `scaffold-sources.py` writes every graph-derivable part of a source page (frontmatter, `source_hash`, symbol table, Depends On, Used By) into `BEGIN`/`END` fences, leaving Purpose and Notes as prose. Same index in, same bytes out; prose and hand-added frontmatter survive regeneration. A missing fence is repaired by appending under its heading, never by stamping a fresh `source_hash` over a section that did not regenerate.
- **Grounding is now checked, not claimed** — `verify-grounding.py` resolves every `realized_by` entry against the index and exits non-zero on failure, so the **Symbols** column in `index.md` reports verified evidence rather than an unchecked count.
- **Change-driven re-ingest** — `check-sources.py --mode code` compares each file's codegraph `content_hash` against the `source_hash` on its wiki page, so refactored files resurface instead of going stale.

### Fixes

- **code-ingest** — Cold-start path was unusable: the documented `codegraph -p` flag does not exist (the path is positional), `index` fails before `init`, and `check-sources.py` demanded a `Wiki/` directory that the first ingest is supposed to create. The `calls` query also lacked `DISTINCT` (one row per call site, not per edge) and the symbol query omitted `constant`, dropping module-level API surface.
- **code-ingest** — Edge queries suppress `idx_edges_kind`, whose poor selectivity on the largest edge kind caused a near-full edge scan per file (8.6s vs 38ms on a 275-file repo when `ANALYZE` stats are absent).
- **wiki-ingest** — Migrated to the shared `check-sources.py`, which adds content-hash change detection: an edited clipping now resurfaces for re-ingest instead of being treated as done.
- **wiki-lint** — Wikilinks inside code spans and fenced blocks are no longer reported as broken links. Obsidian renders these as literal text, so quoted example links and Dataview queries containing `[[...]]` were false positives.

---

## v1.2.0 (2026-04-05)

Renamed project from Agent Toolkit to **Agent Skills**. Retired the monolithic obsidian skill in favor of focused wiki skills and a standalone annotation skill.

### New Skills

- **annotate** — Annotate git commits with structured context using gh-annotate.
- **wiki-ingest** — Ingest raw sources into the LLM wiki from Clippings or Twitter exports.
- **wiki-lint** — Health-check the LLM wiki for broken links, orphan pages, stale content, and missing cross-references.

### Breaking Changes

- **obsidian** skill retired — replaced by wiki-ingest and wiki-lint for wiki workflows; vault management now handled by separate obsidian-cli and obsidian-markdown skills.
- Project renamed: `agent-toolkit` → `agent-skills`.

---

## v1.1.0 (2026-03-08)

Added specification and BDD skills; improved kanban card management.

### New Skills

- **openspec-to-gherkin** — Generate Cucumber/Gherkin feature files from OpenSpec delta specifications.
- **gherkin-step-scaffold** — Generate skeleton step definition files from Gherkin feature files.

### Kanban Improvements

- Card descriptions via `--description` flag and `@filepath` syntax.
- `get` and `delete` commands for full card CRUD.
- Linked note support for rich card descriptions.
- `promote` command for atomic Backlog→Ready moves.

### Fixes

- Fixed typos config to allowlist `SHAL` identifier and prevent `SHALLs` mangling.

---

## v1.0.0 (2026-02-28)

Initial release of the Agent Skills collection — portable skills for AI coding agents.

### Skills

- **obsidian** — Read, write, search, and manage Obsidian vault notes using the native Obsidian CLI. Includes scripts for daily notes, task management, incident tracking, and agent mission control (kanban). *(Retired in v1.2.0)*
- **hk-setup** — Set up [hk](https://github.com/jdx/hk) git hooks with pre-commit linters. Detects project type and configures appropriate tools.
- **mise-setup** — Set up [mise](https://mise.jdx.dev/) dev tool version manager. Configures tools, virtual environments, and tasks for your project.
- **jenkins-migrate** — Convert Jenkins pipelines (Jenkinsfiles) to GitHub Actions workflows.
- **zensical-setup** — Generate documentation sites using [Zensical](https://zensical.dev/).
