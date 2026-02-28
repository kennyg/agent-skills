# Todo Tracking Reference

Task management using [Obsidian Tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) plugin format.

## Commands

```bash
bun scripts/todo.ts <command> [args]
```

| Command                                                | Description                       |
| ------------------------------------------------------ | --------------------------------- |
| `add <text> [tags...] [--due DATE] [--priority LEVEL]` | Add a task                        |
| `done <number or search>`                              | Mark task complete                |
| `delete <number or search>`                            | Remove task entirely              |
| `list [filter]`                                        | Show pending tasks                |
| `all`                                                  | Show pending + recently completed |

## Examples

```bash
# Add tasks
todo add "Review PR" work --due tomorrow --priority high
todo add "Buy groceries" personal errands
todo add "Call mom" --due 2025-12-31

# Complete by number or search
todo done 1
todo done "PR"

# Delete
todo delete 2
todo delete "groceries"

# List and filter
todo list
todo list work
todo all
```

## Options

### Priority

- `--priority high` or `-p h` → ⏫
- `--priority medium` or `-p med` → 🔼
- `--priority low` or `-p l` → 🔽

### Due Date

- `--due today`
- `--due tomorrow`
- `--due 2025-12-31`

## Task Format

Tasks are stored in Obsidian Tasks plugin format:

```markdown
- [ ] Review PR #work ⏫ 📅 2025-12-30 ➕ 2025-12-29
- [ ] Buy groceries #personal #errands ➕ 2025-12-29
- [x] Completed task ➕ 2025-12-28 ✅ 2025-12-29
```

### Emoji Reference

| Emoji | Meaning         |
| ----- | --------------- |
| `⏫`  | High priority   |
| `🔼`  | Medium priority |
| `🔽`  | Low priority    |
| `📅`  | Due date        |
| `➕`  | Created date    |
| `✅`  | Completion date |

## File Location

Default: `Inbox/Tasks.md`

Configure via environment variable:

```bash
export OBSIDIAN_TODO_FILE="Tasks/todo.md"
```

## Task Sorting

Tasks are sorted by:

1. Priority (high → medium → low → none)
2. Due date (earliest first)

List numbers correspond to this sorted order for `done` and `delete` commands.

## Obsidian Tasks Plugin Queries

In Obsidian, query tasks with code blocks:

````markdown
```tasks
not done
due before tomorrow
priority is high
```
````

### Query Examples

```tasks
# All incomplete tasks
not done

# High priority
not done
priority is high

# Due this week
not done
due after today
due before in 7 days

# By tag
not done
tags include #work

# From specific file
not done
path includes Inbox/Tasks
```

See [Tasks plugin docs](https://publish.obsidian.md/tasks/Queries/About+Queries) for full query syntax.
