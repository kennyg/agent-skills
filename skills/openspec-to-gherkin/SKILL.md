---
name: openspec-to-gherkin
description: Generate Cucumber/Gherkin feature files from OpenSpec delta specifications. Use when the user wants to translate OpenSpec specs (with [ADDED]/[CHANGED]/[REMOVED] tags and SHALL/SHALL NOT language) into BDD feature files, create Gherkin scenarios from spec sections, or convert requirements into executable test specifications. Also scaffolds new OpenSpec artifacts from templates. Triggers on requests like "generate features from spec", "convert spec to gherkin", "create cucumber tests from openspec", "translate delta spec to BDD", or "create a new openspec feature".
---

# OpenSpec to Gherkin Generator

Generate Cucumber feature files from OpenSpec delta specifications, with deterministic parsing and traceability validation.

## Workflow

### 1. Parse the spec

Run the parser to get structured data:

```bash
npx tsx <skill-dir>/scripts/parse_spec.ts <path-to-spec.md>
```

This outputs JSON with all sections, tags, SHALL/SHALL NOT statements, quoted strings, and bullet lists. See `<skill-dir>/references/parsed_spec_schema.md` for the full output schema. Use this structured output — not the raw markdown — as the source for generating Gherkin.

### 2. Generate Gherkin from parsed output

Apply the mapping rules below to translate each parsed section into feature files.

### 3. Validate traceability

After generating features, run:

```bash
npx tsx <skill-dir>/scripts/validate_traceability.ts <spec-path> <features-dir>
```

This reports coverage gaps. Fix any "Missing" or "Low coverage" sections before finishing.

## Mapping Rules

| Parsed JSON Field | Gherkin Output |
|---|---|
| Top-level section (level 2) | `Feature:` block |
| Subsection with tag (level 3) | `Scenario:` block(s) |
| `shall[]` entries | `Then` steps (positive assertions) |
| `shallNot[]` entries | `Then` steps (negative assertions) |
| `prose[]` entries (preconditions) | `Given` steps |
| `lists[]` with validation rules | `Scenario Outline` + `Examples` rows |
| `quotedStrings[]` | Exact message text in `Then` steps |
| `tag: "REMOVED"` | Skip entirely |

## Gherkin Guidelines

- Start every `Feature:` with user story: `As a <role>, I want <goal>, So that <benefit>`
- Add `# Spec ref: Section X.Y — Title [TAG]` comment above each scenario group
- Use quoted strings for exact spec messages: `Then I should see the message "exact text"`
- Use `Scenario Outline` with `Examples` table for validation rule lists
- Use `Background:` when multiple scenarios share identical `Given` steps
- Tag scenarios with `@wip` when they depend on unavailable external services

## Feature File Organization

```
features/<topic>/
  <logical-group>.feature    # snake_case, one per major spec section
```

## References

- `<skill-dir>/references/spec_format.md` — rules for writing spec markdown that the parser handles correctly
- `<skill-dir>/references/parsed_spec_schema.md` — TypeScript interfaces and examples for parser output

## Scaffolding New OpenSpec Features

When starting a new feature from scratch, copy the templates:

- `<skill-dir>/assets/templates/proposal.md` → `openspec/changes/<feature>/proposal.md`
- `<skill-dir>/assets/templates/spec.md` → `openspec/changes/<feature>/specs/<name>.md`
- `<skill-dir>/assets/templates/tasks.md` → `openspec/changes/<feature>/tasks.md`

## Arguments

- `/openspec-to-gherkin` — interactively ask which spec to convert
- `/openspec-to-gherkin <path-to-spec.md>` — convert the specified spec
- `/openspec-to-gherkin --new <feature-name>` — scaffold a new OpenSpec feature from templates
