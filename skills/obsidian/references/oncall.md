# Oncall Tracking Reference

Lightweight incident logging with multi-day shift support.

## Commands

```bash
bun scripts/oncall.ts <command> [args]
```

| Command                   | Description                            |
| ------------------------- | -------------------------------------- |
| `start`                   | Start a new oncall shift               |
| `end`                     | End current shift and archive          |
| `log <msg> [tags...]`     | Log an incident                        |
| `resolve <msg> [tags...]` | Log a resolution (auto-adds #resolved) |
| `summary`                 | Show current shift summary with stats  |
| `search <query>`          | Search oncall logs                     |
| `list`                    | List recent shifts                     |

## Examples

```bash
# Start shift
oncall start

# Log incidents with tags
oncall log "PagerDuty alert for db-prod-01" incident database

# Log resolution (auto-adds #resolved)
oncall resolve "Increased connection pool to 50" database

# View summary
oncall summary

# Search logs
oncall search database
oncall search incident

# End shift (archives to dated file)
oncall end
```

## File Structure

```
Journal/Oncall/
├── current-shift.md              # Active shift (created by start)
└── archive/
    ├── 2025-12-29.md             # Single-day shift
    └── 2025-12-25-to-2025-12-27.md  # Multi-day shift
```

## Shift Format

```markdown
---
startDate: 2025-12-29
startTime: 09:00
endDate: 2025-12-29
endTime: 17:00
status: ended
---

## Oncall Shift (2025-12-29)
> Started: 09:00
- 09:15 PagerDuty alert for db-prod-01 #incident #database
- 09:45 ✓ Increased connection pool #resolved #database
> Ended: 17:00
```

## Frontmatter Fields

| Field       | Description                   |
| ----------- | ----------------------------- |
| `startDate` | Shift start date (YYYY-MM-DD) |
| `startTime` | Shift start time (HH:MM)      |
| `endDate`   | Shift end date                |
| `endTime`   | Shift end time                |
| `status`    | `active` or `ended`           |

## Querying with Dataview

```dataview
TABLE startDate, endDate,
  length(filter(file.lists, (x) => contains(x.text, "#incident"))) as Incidents
FROM "Journal/Oncall/archive"
WHERE status = "ended"
SORT startDate DESC
```
