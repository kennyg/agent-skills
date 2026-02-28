# Kanban Agent Mission Control Reference

Programmatic interface for agents to interact with [obsidian-kanban](https://github.com/mgmeyers/obsidian-kanban) boards. Agents claim tasks, update status, and report results — all through the board's markdown file, which Obsidian re-renders live.

## Setup

1. Copy `Agents/Mission-Control.md` board template into your vault (or use any kanban board)
2. Install the [obsidian-kanban plugin](https://github.com/mgmeyers/obsidian-kanban)
3. Enable the CSS snippet: `obsidian snippet:enable name=agent-mission-control`
4. Set `OBSIDIAN_VAULT` in your environment (optional — defaults to active vault)

## Commands

```bash
bun scripts/kanban.ts <command> [args]
```

| Command                                                                                                      | Description                       |
| ------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| `board-status --board <path>`                                                                                | Lane summary with item counts     |
| `list --board <path> [--lane <name>] [--agent <name>]`                                                       | List items as JSON                |
| `get --board <path> --id <blockId>`                                                                          | Get full card + body/linked note  |
| `claim --board <path> --id <blockId> --agent <name>`                                                         | Claim task, move to In Progress   |
| `update --board <path> --id <blockId> --status <value> [--note <text>]`                                      | Update status in place            |
| `complete --board <path> --id <blockId>`                                                                     | Mark done, move to Done lane      |
| `fail --board <path> --id <blockId> [--reason <text>]`                                                       | Move to Failed lane               |
| `add-task --board <path> --title <text> --lane <name> [--priority high\|medium\|low] [--fields key=val,...] [--description <text>]` | Add a new card |
| `delete --board <path> --id <blockId> [--delete-note]`                                                       | Remove card (and optional note)   |

All commands output JSON to stdout. Errors go to stderr with a non-zero exit code.

## Agent Workflow

### 1. Check what's available

```bash
# Overview of all lanes
bun scripts/kanban.ts board-status --board "Agents/Mission-Control.md"

# List unclaimed tasks in Ready
bun scripts/kanban.ts list --board "Agents/Mission-Control.md" --lane Ready
```

### 2. Claim a task

```bash
bun scripts/kanban.ts claim \
  --board "Agents/Mission-Control.md" \
  --id abc123def \
  --agent claude-1
# → moves card to In Progress, adds [agent::claude-1] [status::in-progress] [claimed_at::DATE]
```

### 3. Read the full card

```bash
bun scripts/kanban.ts get \
  --board "Agents/Mission-Control.md" \
  --id abc123def
# → returns title, fields, tags, noteLink, and body (Goal, Acceptance Criteria, DoD)
```

### 4. Update status while working

```bash
bun scripts/kanban.ts update \
  --board "Agents/Mission-Control.md" \
  --id abc123def \
  --status blocked \
  --note "Waiting on API credentials"
```

### 5. Complete or fail

```bash
# Success
bun scripts/kanban.ts complete \
  --board "Agents/Mission-Control.md" \
  --id abc123def

# Failure
bun scripts/kanban.ts fail \
  --board "Agents/Mission-Control.md" \
  --id abc123def \
  --reason "Build failed: missing dependency"
```

## Card Formats

### Simple card

```markdown
- [ ] Task title [agent::claude-1] [status::in-progress] [priority::high] #agent-task #in-progress ^abc123def
```

### Linked note card (preferred for tasks with descriptions)

```markdown
- [ ] [[Task title]] [agent::claude-1] [status::in-progress] [priority::high] #agent-task #in-progress ^abc123def
```

The card title is a wikilink — clicking it opens the full task note in Obsidian. The note lives at `OBSIDIAN_KANBAN_NOTES/{title}.md` (default: `Agents/Tasks/`). `get` reads the note and returns it as `body`.

| Part                               | Purpose                                                 |
| ---------------------------------- | ------------------------------------------------------- |
| `[[Title]]`                        | Wikilink to task note (Goal, Acceptance Criteria, DoD)  |
| `[agent::name]`                    | Which agent claimed this                                |
| `[status::value]`                  | Current status (in-progress, blocked, complete, failed) |
| `[priority::value]`                | high / medium / low                                     |
| `[claimed_at::DATE]`               | ISO date when claimed                                   |
| `#agent-task`                      | Marks card as agent-managed (used by CSS)               |
| `#in-progress` / `#blocked` / etc. | Status tag — drives colored left border via CSS         |
| `^abc123def`                       | Block ID — stable identifier for all CLI operations     |

## Board Lanes

```
Backlog → Ready → In Progress → Blocked → Done → Failed
```

- **Backlog** — ideas, not ready to work
- **Ready** — scoped and claimable by agents
- **In Progress** — claimed and active
- **Blocked** — waiting on something external
- **Done** — completed (`[x]`)
- **Failed** — did not succeed

## Dispatching Tasks to Agents

Add tasks to the Ready lane. Use `--description` to create a linked note with acceptance criteria and definition of done — the card stays clean on the board, full details open on click:

```bash
bun scripts/kanban.ts add-task \
  --board "Agents/Mission-Control.md" \
  --title "Refactor auth module" \
  --lane Ready \
  --priority high \
  --description "**Goal:** Extract auth logic into a standalone module.

**Acceptance Criteria:**
- [ ] Auth logic lives in src/auth/
- [ ] Existing tests still pass

**Definition of Done:**
- [ ] Tests pass
- [ ] PR merged to main
- [ ] Board card marked complete"
```

This creates `Agents/Tasks/Refactor auth module.md` with the description, and the card title becomes `[[Refactor auth module]]`.

See [templates/kanban-task.md](../templates/kanban-task.md) for the full task template.

## Environment

```bash
export OBSIDIAN_VAULT="icloud-vault"      # Optional — defaults to active vault
export OBSIDIAN_KANBAN_NOTES="Agents/Tasks"  # Optional — folder for linked task notes
```

## Status Values

| Status        | Tag            | CSS Border |
| ------------- | -------------- | ---------- |
| `in-progress` | `#in-progress` | Blue       |
| `blocked`     | `#blocked`     | Orange     |
| `complete`    | `#complete`    | Green      |
| `failed`      | `#failed`      | Red        |

## CSS Snippet

The `agent-mission-control.css` snippet styles cards by status. Location:

```
.obsidian/snippets/agent-mission-control.css
```

Enable once via:

```bash
obsidian snippet:enable name=agent-mission-control
```

Requires the [obsidian-kanban plugin](https://github.com/mgmeyers/obsidian-kanban) fork at [`kennyg/obsidian-kanban`](https://github.com/kennyg/obsidian-kanban) for full `[data-metadata-value]` CSS targeting (optional — tag-based coloring works without it).

## Scripts

Scripts live in [`kennyg/agent-toolkit`](https://github.com/kennyg/agent-toolkit) under `skills/obsidian/scripts/kanban.ts`.
