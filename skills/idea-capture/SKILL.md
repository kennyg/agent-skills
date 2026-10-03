---
name: idea-capture
description: "Capture an idea into an Obsidian vault as one note in Ideas/ plus a backlog line in Inbox/Tasks.md. Use when the user says /idea-capture, 'capture this idea', 'save this idea', 'add to my ideas', or 'idea:' followed by a thought, in a vault that has Inbox/Tasks.md."
---

# Idea Capture

Save one idea as a short note in `Ideas/`. Add one task line to `Inbox/Tasks.md`. The `Ideas/Ideas.base` view is the backlog.

The vault root is `$CLAUDE_PROJECT_DIR`, or the current directory if that is unset. Pass `--vault <path>` to the script to override both.

## Workflow

### 1. Read the vault conventions

Read the vault's `CLAUDE.md`. If it defines idea conventions (folder, frontmatter, statuses), follow it and ignore any conflicting default below.

### 2. Check for duplicates

Look for close matches in `Wiki/concepts/` and `Ideas/`:

```bash
<skill-dir>/scripts/idea.py find "<short title>"
```

The command prints the slug and each match as `kind`, score, and path. Then read the matches.

- If an `idea` match says the same thing, update that note. Add the new angle under its open questions. Stop here.
- If a `concept` match covers the topic, create the idea and link the concept in `--related`.
- If nothing matches, go on.

The lookup compares file names only. Also scan `Wiki/index.md` for related entities and concepts under other names.

### 3. Write the note and the task

```bash
<skill-dir>/scripts/idea.py new \
  --title "<title>" \
  --idea "<one sentence>" \
  --why "<why it matters>" \
  --question "<open question>" \
  --source "<URL or [[wikilink]]>" \
  --related "<concept or entity name>"
```

The script does four things.

1. It writes `Ideas/<slug>.md` with `status: captured` and today's date.
2. It installs `Ideas/Ideas.base` if the file is missing.
3. It appends one line to `Inbox/Tasks.md`.
4. It stops with an error if `Ideas/<slug>.md` exists.

Repeat `--question`, `--related` and `--tag` as needed. Omit `--source` if there is none. Pass `--no-task` if the user does not want a backlog line.

### 4. Link related notes

Add inline `[[wikilinks]]` to the note body where the idea touches a concept or entity. Use the note name only, not the path. Do not edit `Wiki/` pages. Any `Wiki/` edit needs an index and log update, so leave them alone.

### 5. Report

Give the path of the note, the task line, and any match you linked or updated.

## Note format

```markdown
---
type: idea
status: captured
date_captured: 2026-10-03
tags:
  - idea
source: "https://example.com"
---

One sentence that states the idea.

## Why it matters

One or two sentences.

## Open questions

- A question that blocks a decision.
```

`status` is one of `captured`, `exploring`, `parked`, `done`. Change it by hand or by edit as work moves. `source` is optional.

## Backlog line

```markdown
- [ ] Explore idea [[<slug>|<title>]] #idea ➕ 2026-10-03
```

This matches the emoji format of the Tasks plugin. Add `⏫` or `📅` only if the user gives a priority or date.

## Rules

- Write one note per idea. Never merge two ideas into one note.
- Keep the note short. Three sections at most, plus `Related`.
- Never invent a source. Omit `source` if the user gave none.
- Never edit `Clippings/`, `Twitter-Captures/` or `Wiki/`.
- Keep the Base file as installed. Change views in Obsidian, not through this skill.
- Preserve frontmatter delimiters, Dataview queries and `^blockid` references in any note you edit.
