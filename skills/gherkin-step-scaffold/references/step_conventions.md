# Step Definition Conventions

## Naming Patterns

Use consistent, reusable step patterns across features. Prefer generic patterns that work across multiple scenarios over feature-specific wording.

### Given Steps (Preconditions)

```
# Navigation
I am on the {string} page

# Entity existence
a/an {string} exists with {string} {string}
  e.g., "a user exists with email "alice@example.com""

no {string} exists with {string} {string}
  e.g., "no account exists with email "nobody@example.com""

# State setup
I have a valid {string}
  e.g., "I have a valid reset token"

I have not {past_action}
  e.g., "I have not verified my email"

# Quantified preconditions
{int} {event_description} in the last {string}
  e.g., "3 password reset requests have been made for "user@example.com" in the last hour"
```

### When Steps (Actions)

```
# Form input
I enter {string} as the {string}
  e.g., "I enter "alice@example.com" as the email"

I leave the {string} field empty

# Button/form submission
I click the {string} button
I submit the {string} form

# Navigation
I navigate to the {string} page
I navigate to the {string} with {string}
```

### Then Steps (Assertions)

```
# Message display
I should see the message {string}
I should see the inline error {string}
I should see an inline error indicating {string}

# Visibility
I should see {string}
I should not see {string}

# Navigation result
I should be redirected to the {string} page

# State assertions
the {string} should be {string}
  e.g., "the account should be verified"

# Negative assertions (from SHALL NOT)
the system should not {string}
the form should not be submitted
```

## Parameter Types

| Cucumber Type | Use For | Example |
|---|---|---|
| `{string}` | Any quoted value | email addresses, messages, button labels |
| `{int}` | Whole numbers | counts, status codes, hours |
| `{float}` | Decimal numbers | rates, percentages |

## File Organization Rules

1. **One step definition file per feature topic** — name as `<topic>_steps.js`
2. **Shared steps** go in the most semantically relevant file, not a catch-all `common_steps.js`
3. **Group by step type** within each file: Given first, then When, then Then
4. **Never duplicate** a step pattern across files — Cucumber will error on ambiguous matches

## Avoiding Duplicates

Before defining a step, check if an existing pattern already matches:

- `I should see the message {string}` handles ALL exact message assertions
- `I enter {string} as the {string}` can handle email, password, name fields
- `I should be redirected to the {string} page` handles all redirects

Prefer one parameterized step over multiple specific steps:

```javascript
// GOOD: one step handles all message assertions
Then('I should see the message {string}', function (message) { ... });

// BAD: separate steps for each message
Then('I should see the success message', function () { ... });
Then('I should see the error message', function () { ... });
```
