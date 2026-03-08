# OpenSpec Delta Spec Format

Rules for writing delta spec markdown that `parse_spec.ts` can parse correctly.

## Document Structure

```
# <Spec Title>                          → parsed as `title`

## <N>. <Section Name>                  → level 2, groups child sections
## <Section Name> [TAG]                 → level 2 with tag, standalone section

### <N.M> <Subsection Name> [TAG]       → level 3 with tag, primary unit of work
```

## Heading Rules

| Element | Format | Required | Example |
|---|---|---|---|
| Spec title | `# Title` (h1) | Yes | `# Password Reset Specification` |
| Major section | `## N. Name` or `## Name [TAG]` | Yes | `## 1. Reset Request Form` |
| Subsection | `### N.M Name [TAG]` | Yes for tagged | `### 1.1 Form Fields [ADDED]` |
| Section number | Dot-separated digits | No, but needed for traceability | `1`, `1.1`, `2.3` |
| Tag | `[ADDED]`, `[CHANGED]`, or `[REMOVED]` at end | Required for sections with requirements | `[ADDED]` |

## Body Content

Within a section (between headings), the parser recognizes:

### SHALL Statements (paragraphs containing `SHALL`)

```markdown
The system SHALL validate that the email field is not empty.
```

- Parsed into `shall[]` array
- Quoted strings (`"text"` or `\u201ctext\u201d`) extracted into `quotedStrings[]`
- Each becomes one or more `Then` steps in Gherkin

### SHALL NOT Statements (paragraphs containing `SHALL NOT` but not a positive `SHALL`)

```markdown
The system SHALL NOT submit the form when the email is invalid.
```

- Parsed into `shallNot[]` array
- If a paragraph has both `SHALL` and `SHALL NOT`, it goes into `shall[]` (the positive array)

### Bullet Lists

```markdown
- Minimum 8 characters in length
- At least one uppercase letter (A-Z)
```

- Parsed into `lists[]` as arrays of strings
- Typically used for validation rules, field lists, or enumerated requirements
- When paired with a SHALL statement, suggests `Scenario Outline` with `Examples`

### Prose (all other paragraphs)

```markdown
The password reset form provides a way for users to regain account access.
```

- Parsed into `prose[]` array
- Non-requirement context: descriptions, rationale, notes

## Tags

| Tag | Meaning | Gherkin Action |
|---|---|---|
| `[ADDED]` | New behavior | Generate scenarios |
| `[CHANGED]` | Modified behavior | Generate scenarios with change context |
| `[REMOVED]` | Deleted behavior | Skip — do not generate scenarios |

## Section Hierarchy

Level 2 sections without tags serve as **grouping parents** for level 3 children:

```markdown
## 1. Reset Request Form              ← no tag, groups children below
### 1.1 Form Fields [ADDED]           ← tagged, has requirements
### 1.2 Email Validation [ADDED]      ← tagged, has requirements
```

Level 2 sections WITH tags are **standalone** — they contain requirements directly:

```markdown
## 2. Reset Token [ADDED]             ← tagged, has own requirements
```

## Parent Number Derivation

The parser derives `parentNumber` from section numbers:

| Section Number | Parent Number |
|---|---|
| `1` | `null` |
| `1.1` | `1` |
| `1.2` | `1` |
| `2.3.1` | `2.3` |
