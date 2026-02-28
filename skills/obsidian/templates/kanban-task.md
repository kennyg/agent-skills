# Kanban Task Template

Use this structure when dispatching tasks to agents via `add-task --description`.

When `--description` is provided, the CLI automatically:
- Creates a note at `Agents/Tasks/{title}.md` with the description
- Sets the card title to `[[title]]` (wikilink) so it opens in Obsidian on click
- `get` reads the note and returns the body to agents

## Description Format

```
**Goal:** <What needs to be accomplished — one sentence>

**Acceptance Criteria:**
- [ ] <Specific, testable criterion>
- [ ] <Another criterion>

**Definition of Done:**
- [ ] Output verified / tests pass
- [ ] Changes committed and pushed
- [ ] Board card marked complete
```

## Example

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
- [ ] No circular imports

**Definition of Done:**
- [ ] Tests pass
- [ ] PR merged to main
- [ ] Board card marked complete"
```

Creates card on board:
```markdown
- [ ] [[Refactor auth module]] [priority::high] #agent-task ^blockid
```

And note at `Agents/Tasks/Refactor auth module.md` with the full description.

## Agent Reading Pattern

After claiming a task, agents read the full card with:

```bash
bun scripts/kanban.ts get --board "Agents/Mission-Control.md" --id <blockId>
```

Response includes `noteLink` and `body` — agents should read `body` to understand the Goal, Acceptance Criteria, and Definition of Done before starting work.

## Fields Reference

| Flag            | Required | Values                        |
| --------------- | -------- | ----------------------------- |
| `--title`       | Yes      | Short imperative phrase       |
| `--lane`        | Yes      | `Backlog`, `Ready`            |
| `--priority`    | No       | `high`, `medium`, `low`       |
| `--description` | No       | Multi-line body (creates note)|
| `--fields`      | No       | `key=val,...` custom fields   |
