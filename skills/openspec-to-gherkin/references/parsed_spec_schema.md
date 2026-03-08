# parse_spec.ts Output Schema

TypeScript interfaces defining the JSON output of `parse_spec.ts`.

## Interfaces

```typescript
interface ParsedSpec {
  title: string;           // From the h1 heading
  sections: SpecSection[]; // All h2/h3 sections in document order
}

interface SpecSection {
  number: string | null;       // "1.1", "2.3" — null if no number in heading
  title: string;               // Heading text without number and tag
  tag: "ADDED" | "CHANGED" | "REMOVED" | null;
  level: 2 | 3;               // h2 = 2, h3 = 3
  parentNumber: string | null; // "1" for section "1.1", null for top-level

  shall: ShallStatement[];     // Paragraphs containing SHALL (positive)
  shallNot: ShallStatement[];  // Paragraphs containing SHALL NOT only
  lists: string[][];           // Bullet lists, each list is array of items
  prose: string[];             // Non-requirement paragraphs
}

interface ShallStatement {
  text: string;              // Full paragraph text
  quotedStrings: string[];   // Extracted "quoted" or \u201cquoted\u201d values
}
```

## Example

Given this spec section:

```markdown
### 1.2 Email Validation [ADDED]

The system SHALL validate that the email field is not empty.

The system SHALL display an inline error message "Please enter a valid email address" when the email is invalid.

The system SHALL NOT submit the form when the email is invalid.
```

The parser outputs:

```json
{
  "number": "1.2",
  "title": "Email Validation",
  "tag": "ADDED",
  "level": 3,
  "parentNumber": "1",
  "shall": [
    {
      "text": "The system SHALL validate that the email field is not empty.",
      "quotedStrings": []
    },
    {
      "text": "The system SHALL display an inline error message \"Please enter a valid email address\" when the email is invalid.",
      "quotedStrings": ["Please enter a valid email address"]
    }
  ],
  "shallNot": [
    {
      "text": "The system SHALL NOT submit the form when the email is invalid.",
      "quotedStrings": []
    }
  ],
  "lists": [],
  "prose": []
}
```

## Key Behaviors

- **SHALL vs SHALL NOT**: If a paragraph contains both `SHALL` and `SHALL NOT`, it is classified as `shall` (positive). Only pure `SHALL NOT` paragraphs go into `shallNot`.
- **Quoted strings**: Both `"straight quotes"` and `\u201csmart quotes\u201d` are extracted.
- **Markdown stripping**: Bold, italic, inline code are stripped — output is plain text.
- **Lists are separate**: Bullet list items are never included in `shall` or `prose`. They appear only in `lists`.
