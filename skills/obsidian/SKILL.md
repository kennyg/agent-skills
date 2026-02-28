---
name: obsidian
description: "Read, write, search, and manage Obsidian vault notes. Use when: (1) Reading/writing markdown notes, (2) Searching vault content, (3) Managing daily/periodic notes, (4) Tracking tasks or oncall incidents. Uses the native Obsidian CLI."
license: MIT
metadata:
  author: Kenny Gatdula
  version: "2.0.0"
  tags: obsidian, notes, vault, tasks, kanban, agents, productivity
  compatibility: Any agentskills.io-compatible agent
---

# Obsidian Vault Integration

Uses the native Obsidian CLI — no plugins or API keys needed.

## Configuration

```bash
export OBSIDIAN_VAULT="my-vault"       # Optional — defaults to active vault
export OBSIDIAN_TODO_FILE="Inbox/Tasks.md"  # Optional
```

## CLI Tools

### Native Obsidian CLI

```bash
obsidian read path=<path>                       # Read note
obsidian create path=<path> content=<text> overwrite  # Write note
obsidian search query=<text>                    # Search vault
obsidian daily:read                             # Read daily note
obsidian daily:append content=<text>            # Append to daily note
obsidian command id=<id>                        # Execute command
obsidian snippet:enable name=<name>             # Enable CSS snippet
obsidian files                                  # List vault files
```

### Thought (Daily Notes)

```bash
thought "Great idea for the app"
thought "Meeting went well" meeting work
```

### Todo Tracking

```bash
todo add "Review PR" work --due tomorrow --priority high
todo done 1                    # Complete by number
todo done "PR"                 # Complete by search
todo delete 2                  # Remove task
todo list                      # Show pending
todo list work                 # Filter by tag
```

See: [references/todo.md](references/todo.md)

### Oncall Tracking

```bash
oncall start                   # Start shift
oncall log "Alert fired" incident database
oncall resolve "Fixed it" database
oncall summary                 # View current shift
oncall end                     # End and archive
```

See: [references/oncall.md](references/oncall.md)

### Agent Mission Control (Kanban)

```bash
bun scripts/kanban.ts board-status --board "Agents/Mission-Control.md"
bun scripts/kanban.ts list --board "Agents/Mission-Control.md" --lane Ready
bun scripts/kanban.ts claim --board "Agents/Mission-Control.md" --id <blockId> --agent <name>
bun scripts/kanban.ts update --board "Agents/Mission-Control.md" --id <blockId> --status blocked
bun scripts/kanban.ts complete --board "Agents/Mission-Control.md" --id <blockId>
bun scripts/kanban.ts fail --board "Agents/Mission-Control.md" --id <blockId> --reason "..."
bun scripts/kanban.ts add-task --board "Agents/Mission-Control.md" --title "..." --lane Ready
```

See: [references/kanban.md](references/kanban.md)

## Decision Guide

| Need                      | Method             |
| ------------------------- | ------------------ |
| Read/write notes          | `obsidian` CLI     |
| Search vault              | `obsidian` CLI     |
| Execute commands/snippets | `obsidian` CLI     |
| Quick thoughts/notes      | `thought` CLI      |
| Task management           | `todo` CLI         |
| Oncall/incidents          | `oncall` CLI       |
| Agent task dispatch/claim | `kanban` CLI       |

## Reference Docs

- [Obsidian CLI Reference](references/obsidian-cli.md) - Native CLI commands
- [Thought Reference](references/thought.md) - Quick notes to daily journal
- [Todo Reference](references/todo.md) - Task management with Obsidian Tasks format
- [Oncall Reference](references/oncall.md) - Incident tracking and shift management
- [Kanban Reference](references/kanban.md) - Agent mission control and task dispatch
