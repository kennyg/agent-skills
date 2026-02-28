# Thought CLI Reference

Quick notes to your daily journal with optional tags.

## Usage

```bash
bun scripts/thought.ts <message> [tags...]
```

## Examples

```bash
# Simple thought
thought "Great idea for the app"

# With tags
thought "Meeting went well" meeting work
thought "Remember to call mom" personal reminder
thought "Bug in auth flow" bug backend urgent
```

## Output Format

Entries are appended to your daily note:

```markdown
- 10:25 Great idea for the app
- 10:30 Meeting went well #meeting #work
- 14:15 Remember to call mom #personal #reminder
```

## Daily Note Location

Uses Obsidian's own daily note settings (Periodic Notes or Daily Notes plugin). No extra configuration needed.

## Shell Alias

Add to `.zshrc` or `.bashrc`:

```bash
alias thought="bun /path/to/obsidian-skill/scripts/thought.ts"
```

## Tips

- Use consistent tags for easy searching (`#idea`, `#meeting`, `#reminder`)
- Tags become Obsidian tags, searchable and clickable in the graph view
- Entries are timestamped with HH:MM format
