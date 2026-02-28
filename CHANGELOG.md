# Changelog

## v1.0.0 (2026-02-28)

Initial release of the Agent Toolkit — a collection of portable skills for AI coding agents.

### Skills

- **obsidian** — Read, write, search, and manage Obsidian vault notes using the native Obsidian CLI. Includes scripts for daily notes (`thought`), task management (`todo`), incident tracking (`oncall`), and agent mission control (`kanban`).
- **hk-setup** — Set up [hk](https://github.com/jdx/hk) git hooks with pre-commit linters. Detects project type and configures appropriate tools.
- **mise-setup** — Set up [mise](https://mise.jdx.dev/) dev tool version manager. Configures tools, virtual environments, and tasks for your project.
- **jenkins-migrate** — Convert Jenkins pipelines (Jenkinsfiles) to GitHub Actions workflows.
- **zensical-setup** — Generate documentation sites using [Zensical](https://zensical.dev/).

### Obsidian Skill Highlights

- Native Obsidian CLI integration — no plugins, no API keys, no MCP server
- **Agent Mission Control** — kanban board as a task queue; agents claim cards, update status, and report results live in Obsidian
- Full script suite: `thought`, `todo`, `oncall`, `kanban`
- Card format: `[agent::name] [status::in-progress] [priority::high] #agent-task ^blockid`
