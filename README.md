# Agent Skills

A collection of portable skills for AI coding agents. Part of the [skills.sh](https://skills.sh/) open ecosystem.

## What are Agent Skills?

Skills are reusable extensions that give AI coding agents specialized capabilities—packaged instructions and scripts that work across multiple agents:

| Agent | Skills Directory |
|-------|------------------|
| Claude Code | `.claude/skills/` |
| GitHub Copilot | `.github/skills/` |
| Cursor | `.cursor/skills/` |
| OpenCode | `.opencode/skills/` |
| Generic | `.agent/skills/` |

## Available Skills

<!-- BEGIN GENERATED SKILLS TABLE -->
| Skill | Description |
|-------|-------------|
| [annotate](skills/annotate/) | Annotate git commits with structured context using gh-annotate |
| [code-ingest](skills/code-ingest/) | Ingest a codegraph-indexed codebase into a repo-local code wiki |
| [gherkin-step-scaffold](skills/gherkin-step-scaffold/) | Generate skeleton step definition files from Cucumber/Gherkin feature files |
| [github-gist](skills/github-gist/) | Create GitHub gists quickly from files, code snippets, or text content |
| [going-ashore](skills/going-ashore/) | Runbook for standing up a first mate and its fleet on a remote host over SSH + herdr ("going ashore") |
| [hk-setup](skills/hk-setup/) | Set up hk (git hook manager) with pre-commit hooks for any project |
| [jenkins-migrate](skills/jenkins-migrate/) | Convert Jenkins pipelines (Jenkinsfiles) to GitHub Actions workflows |
| [mise-setup](skills/mise-setup/) | Set up mise (dev tool version manager) for any project |
| [openspec-to-gherkin](skills/openspec-to-gherkin/) | Generate Cucumber/Gherkin feature files from OpenSpec delta specifications |
| [wiki-ingest](skills/wiki-ingest/) | Ingest raw sources into the LLM wiki |
| [wiki-lint](skills/wiki-lint/) | Health-check the LLM wiki for quality issues |
| [zensical-setup](skills/zensical-setup/) | Generate documentation sites using Zensical (from the creators of Material for MkDocs) |
<!-- END GENERATED SKILLS TABLE -->

## Agent Plugins package

This repo is also a conformant [Agent Plugins](https://agent-plugins.org/)
v1.0.0 package — the vendor-neutral standard for packaging agent extensions
into a distributable unit.

The root `plugin.json` is the manifest. Its `$schema` value declares the spec
version the package targets, and `skills/` is already the spec's fixed
discovery location for Agent Skills, so no restructuring was needed.

```
agent-skills/
├── plugin.json          # Agent Plugins v1.0.0 manifest
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

For consumers, that means any Agent Plugins-conformant client can load this
repo as a single plugin from a directory path, without client-specific path
knowledge — and gets every skill in `skills/` at once. Nothing changes if you
prefer the per-skill workflow below; the two are complementary.

## Installation

Install via [skills.sh](https://skills.sh/):

```bash
npx skills add <owner/repo>
```

Or copy a skill manually to your project or global skills directory:

```bash
# Example: Install github-gist for Claude Code
cp -r skills/github-gist ~/.claude/skills/
```

## Creating Skills

Each skill follows a standard structure:

```
skills/<skill-name>/
├── SKILL.md      # Documentation with frontmatter metadata
└── <scripts>     # Implementation files
```

The `SKILL.md` frontmatter includes:
- `name`: Skill identifier
- `description`: What the skill does (used by agents for tool selection)
- `license`: License type
- `metadata`: Author, version, tags, compatibility info

See [skills.sh](https://skills.sh/) for the full specification and skill directory.

## License

MIT
