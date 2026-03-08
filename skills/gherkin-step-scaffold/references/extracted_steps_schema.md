# extract_steps.ts Output Schema

TypeScript interfaces defining the JSON output of `extract_steps.ts`.

## Interfaces

```typescript
interface ExtractOutput {
  features: FeatureInfo[];
  steps: StepsByType;
  summary: Summary;
  missing?: StepsByType<MissingStep>;   // only with --check
  duplicates?: DuplicateStep[];          // only with --check
}

interface FeatureInfo {
  file: string;           // Relative path from features dir, e.g. "reset_request_form.feature"
  name: string;           // Feature name from the Feature: line
  scenarioCount: number;  // Total scenario instances (Outline rows expanded)
  steps: string[];        // Unique step patterns used in this feature
}

interface StepsByType {
  given: StepDetail[];
  when: StepDetail[];
  then: StepDetail[];
}

interface StepDetail {
  pattern: string;         // Cucumber expression, e.g. "I enter {string} as the {string}"
  params: StepParam[];     // Derived parameter names and types
  usedIn: string[];        // Feature files that use this step
  count: number;           // Total usage count across all features
}

interface StepParam {
  name: string;            // Derived name, e.g. "email", "message", "count"
  type: "string" | "int" | "float";
}

interface Summary {
  totalFeatures: number;
  totalScenarios: number;
  uniqueSteps: {
    given: number;
    when: number;
    then: number;
  };
}

// --check mode only:

interface MissingStep {
  pattern: string;
  params: StepParam[];
  definedIn: null;         // Always null (not found in any definition file)
}

interface DuplicateStep {
  pattern: string;
  definedIn: string[];     // Files where this pattern is defined more than once
}
```

## Pattern Conversion Rules

Step text from feature files is converted to Cucumber expression patterns:

| Feature Text | Pattern |
|---|---|
| `I enter "alice@example.com" as the email` | `I enter {string} as the email` |
| `I have 3 failed attempts` | `I have {int} failed attempts` |
| `the rate is 2.5 per second` | `the rate is {float} per second` |
| `I enter "<password>" as the new password` | `I enter {string} as the new password` |

Conversion order matters: `<angle brackets>` → `"quoted strings"` → `floats` → `integers`.

## Parameter Name Derivation

Parameter names are derived from surrounding words in the pattern:

| Pattern | Derived Name | Rule |
|---|---|---|
| `I enter {string} as the email` | `email` | Word after "as the" |
| `with email {string}` | `email` | Word before placeholder (preposition context) |
| `I should see the message {string}` | `message` | Word before placeholder |
| `I have {int} failed attempts` | `failed` | Word after placeholder (when word before is stop word) |
| `{string}` (no context) | `string` | Fallback to type name |

## And/But Resolution

`And` and `But` keywords inherit the type of the preceding `Given`, `When`, or `Then`:

```gherkin
Given I am logged in
And I have verified my email      ← resolved as Given
When I click submit
And I confirm the dialog          ← resolved as When
Then I should see a message
But I should not see an error     ← resolved as Then
```

## Scenario Outline Expansion

`scenarioCount` expands Scenario Outlines by their Examples rows:

```gherkin
Scenario Outline: Validation       ← counts as 4 scenarios (4 example rows)
  Examples:
    | input    |
    | short    |
    | noCaps   |
    | NOCAPS   |
    | noDigits |
```

## --check Mode

When invoked with `--check <step-defs-dir>`, the script scans `.js` files for step definitions using regex:

```javascript
Given('pattern', function ...)   // matched
When("pattern", function ...)    // matched
Then(`pattern`, function ...)    // matched
```

Steps found in features but not in definitions → `missing`.
Patterns defined in multiple files → `duplicates`.
