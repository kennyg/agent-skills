---
name: gherkin-step-scaffold
description: Generate skeleton step definition files from Cucumber/Gherkin feature files. Use when the user wants to scaffold step definitions, create pending step stubs, generate step definition boilerplate from feature files, or wire up Gherkin steps to code. Also detects missing steps and duplicate definitions. Triggers on requests like "scaffold steps", "generate step definitions", "create step stubs", "wire up features", "stub out cucumber steps", or "check for missing steps".
---

# Gherkin Step Definition Scaffolder

Generate step definition files from feature files, with automated extraction, deduplication, and gap detection.

## Workflow

### 1. Extract and analyze steps

Run the extractor to get structured step data:

```bash
npx tsx <skill-dir>/scripts/extract_steps.ts <features-dir>
```

This outputs JSON with all unique step patterns, parameter types, usage counts, and which features use each step. See `<skill-dir>/references/extracted_steps_schema.md` for the full output schema.

### 2. Check against existing definitions

To find missing steps and duplicates:

```bash
npx tsx <skill-dir>/scripts/extract_steps.ts <features-dir> --check <step-defs-dir>
```

The `missing` array shows steps in features that have no matching definition. The `duplicates` array shows patterns defined in multiple files.

### 3. Generate step definition files

Pipe the extractor output into the stub generator:

```bash
npx tsx <skill-dir>/scripts/extract_steps.ts <features-dir> | npx tsx <skill-dir>/scripts/generate_stubs.ts <output-dir> [--ts]
```

This produces step definition files with:
- One file per feature topic (`<topic>_steps.js`)
- Shared steps in `common_steps.js`
- Grouped by type: Given, then When, then Then
- All stubs return `'pending'`
- Correct parameter names and types

Use `--ts` flag for TypeScript output. See `<skill-dir>/references/step_conventions.md` for naming conventions.

### 4. Verify wiring

After generating, run:

```bash
npx cucumber-js --dry-run 2>&1
```

Fix any undefined steps, duplicate definitions, or ambiguous matches before finishing.

## Output Format

Generate JavaScript (CommonJS) by default. Use TypeScript if the project has `tsconfig.json` or existing `.ts` step definitions.

### JavaScript

```javascript
const { Given, When, Then } = require('@cucumber/cucumber');

Given('pattern with {string} param', function (param) {
  return 'pending';
});
```

### TypeScript

```typescript
import { Given, When, Then } from '@cucumber/cucumber';

Given('pattern with {string} param', function (param: string) {
  return 'pending';
});
```

## References

- `<skill-dir>/references/extracted_steps_schema.md` — TypeScript interfaces and examples for extractor output
- `<skill-dir>/references/step_conventions.md` — step naming patterns and file organization rules

## Arguments

- `/gherkin-step-scaffold` — scaffold for all features in `features/`
- `/gherkin-step-scaffold <features-dir>` — scaffold for a specific directory
- `/gherkin-step-scaffold --check` — only report missing/duplicate steps, don't generate
- `/gherkin-step-scaffold --ts` — generate TypeScript definitions
