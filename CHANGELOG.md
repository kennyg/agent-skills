# Changelog

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
