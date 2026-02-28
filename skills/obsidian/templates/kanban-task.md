# Kanban Task Template

Use this structure when adding tasks to the Mission Control board via `add-task --description`.

## Card Structure

```
- [ ] <Title> [priority::high|medium|low] #agent-task ^<blockid>
    **Goal:** <What needs to be accomplished>

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

## Fields

| Field        | Required | Values                  |
| ------------ | -------- | ----------------------- |
| `--title`    | Yes      | Short imperative phrase |
| `--lane`     | Yes      | Backlog, Ready          |
| `--priority` | No       | high, medium, low       |
| `--description` | No    | Multi-line body text    |
| `--fields`   | No       | `key=val,...` pairs     |
