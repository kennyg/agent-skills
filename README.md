# Agent Toolkit

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

| Skill | Description |
|-------|-------------|
| [github-gist](skills/github-gist/) | Create GitHub gists from files or snippets |
| [hk-setup](skills/hk-setup/) | Set up hk git hooks with pre-commit linters |
| [jenkins-migrate](skills/jenkins-migrate/) | Convert Jenkins pipelines to GitHub Actions |
| [mise-setup](skills/mise-setup/) | Set up mise dev tool version manager |
| [obsidian](skills/obsidian/) | Read, write, search, and manage Obsidian vault notes |
| [zensical-setup](skills/zensical-setup/) | Generate documentation sites using Zensical |

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
