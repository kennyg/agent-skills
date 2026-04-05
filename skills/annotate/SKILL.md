---
name: annotate
description: Annotate git commits with structured context using gh-annotate. Use after making commits, completing tasks, reviewing code, fixing bugs, or making non-obvious design decisions. Triggers on commit workflows, code reviews, refactors, bug fixes, and when the user asks to annotate or leave notes on commits.
---

# Annotate

Leave structured annotations on git commits using `gh-annotate`. Annotations live in git notes (`refs/notes/annotate`) — a sideband channel that doesn't modify commit history.

## When to Annotate

- After a commit with non-obvious design choices
- After a bug fix (document root cause)
- After a refactor (what changed, what was left alone)
- After a review (observations on specific commits)
- When context would help future readers

Do NOT annotate trivial commits (typos, formatting, version bumps).

## Adding Annotations

```bash
gh-annotate add <commit> \
  -m "<1-3 sentences focusing on WHY, not WHAT>" \
  -a "claude" \
  -r agent \
  -t "<tags>"
```

For file-specific context:

```bash
gh-annotate add <commit> \
  -m "Retry logic handles race condition from issue #42" \
  -a "claude" -r agent -t "context,bug-fix" \
  --ref-file pkg/sync/retry.go --ref-lines 58-73
```

Use `--thread <id>` to link related annotations across commits.

## Tags

| Tag | When |
|-----|------|
| `decision` | Non-obvious design choice |
| `trade-off` | Something intentionally deferred or accepted |
| `bug-fix` | Root cause analysis |
| `refactor` | Structural change, no behavior change |
| `review` | Post-review observation |
| `context` | Background knowledge for future readers |
| `perf` | Performance-related change or consideration |

Combine tags: `-t "decision,trade-off"`

## Reading Annotations

Check for existing annotations before working on unfamiliar code:

```bash
gh-annotate log HEAD~10..              # recent
gh-annotate show <commit>              # specific commit
gh-annotate search "retry"             # by content
gh-annotate search "" -r agent -t decision  # by metadata
```

## Guidelines

- Keep annotations to 1-3 sentences
- Focus on *why*, not *what* (the diff shows what)
- Use role `-r agent` for AI-generated annotations
- Set author `-a "claude"` to identify the source
