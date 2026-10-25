---
name: github-harden
description: "Audit the security settings of public GitHub repos and apply a hardened baseline. Use when the user asks to audit, check, lock down or harden their public GitHub repos, to check repo security settings, or to apply rulesets, Dependabot, secret scanning or Actions token limits across many repos."
license: MIT
metadata:
  author: Kenny Gatdula
  version: "1.0.0"
  tags: github, security, hardening, audit, rulesets, dependabot, universal
  compatibility: Any agentskills.io-compatible agent. Needs the gh CLI, logged in with admin access to the repos.
---

# GitHub Harden

Audit the security settings of public GitHub repos against one baseline. Apply the baseline where a repo misses it.

The script reads and writes every setting through `gh api`. Audit is the default mode, and it changes nothing. Apply changes only the settings that differ, and only after it lists them.

## When to use

- The user wants to know which of their public repos are open to outside pull requests, fork CI runs or tag rewrites.
- The user wants one security baseline on every public repo of a user or an org.
- The user made a new public repo and wants it to match the others.

Do not use it for private repos. The script skips them, because several baseline features exist only for public repos.

## Workflow

### 1. Audit

```bash
<skill-dir>/scripts/harden.py                      # every public repo of the gh login
<skill-dir>/scripts/harden.py --owner some-org     # every public repo of a user or org
<skill-dir>/scripts/harden.py my-repo other/repo   # named repos; a bare name uses --owner or the gh login
<skill-dir>/scripts/harden.py --json               # the same audit as JSON
```

The table has one row per repo and one column per setting. A cell reads `ok` when the setting meets the baseline. Otherwise it reads `NO(<current value>)`, such as `NO(all)` or `NO(off)`. A cell reads `n/a` when the repo does not have the feature. The last three columns are report-only items, explained in [Report-only items](#report-only-items).

The JSON output gives `current`, `desired` and `ok` for each setting, the report-only items, the skipped repos and any errors.

Forks and archived repos are skipped. Pass `--include-forks` or `--include-archived` to audit them too. GitHub makes an archived repo read-only, so the script never plans a change for one. The plan prints a `NOTE` line for each archived repo that misses the baseline. Unarchive the repo first to harden it.

### 2. Plan

```bash
<skill-dir>/scripts/harden.py --plan
```

The plan lists each change as `owner/repo: setting current -> desired`. It changes nothing. Show the plan to the user. Read out every `WARNING` line, because each one names people that collaborators-only blocks.

Pass `--skip <setting>` to leave a setting alone, such as `--skip pr_policy`. Repeat it for more settings.

### 3. Apply

Apply only after the user approves the plan. Pass the same scope and `--skip` flags as the plan.

```bash
<skill-dir>/scripts/harden.py --apply --yes
```

Without `--yes`, the script asks for `yes` on a terminal. If no terminal is attached, it stops with no change. After the writes, it reads each changed setting back. It prints `FAILED` for each write that GitHub refused, and for each setting that still differs.

### 4. Report

Give the user the count of changes, each `FAILED` line, and the report-only items that need work.

## Exit status

| Code | Audit and plan | Apply |
|---|---|---|
| `0` | Every repo meets the baseline. | Every change held. |
| `1` | At least one repo misses the baseline. | At least one change failed. |
| `2` | A usage error, or `gh` failed before the audit. | The same, or the user did not confirm. |

## The baseline

The setting names below are the names that `--skip` and the JSON output use.

| Setting | Column | Baseline |
|---|---|---|
| `pr_policy` | `prs` | Only collaborators can open pull requests. |
| `fork_approval` | `fork-ci` | Workflows from fork pull requests of all outside contributors wait for approval. |
| `private_vuln_reporting` | `pvr` | Private vulnerability reporting is on. |
| `vulnerability_alerts` | `alerts` | Dependabot alerts are on. |
| `security_fixes` | `fixes` | Dependabot security updates are on. |
| `workflow_token` | `token` | The default `GITHUB_TOKEN` is read-only and cannot approve pull requests. |
| `ruleset_main` | `main` | The ruleset `Protect main` blocks deletion and force pushes on the default branch. |
| `ruleset_tags` | `tags` | The ruleset `Protect release tags` blocks creation, update, deletion and force pushes of `v*` tags, except for admins. |
| `secret_scanning` | `secrets` | Secret scanning is on. |
| `push_protection` | `push` | Secret scanning push protection is on. |

In each section below, `OWNER/REPO` stands for the repo to change.

### `pr_policy`: collaborators-only pull requests

Why it matters: a pull request from a stranger is the start of most attacks on a repo's CI. Examples are workflow injection, cache poisoning and spam that wears a maintainer out. With this setting, only people you invited can open a pull request.

Cost: outside contributors can no longer open pull requests. They can still read the repo, fork it, and comment on open pull requests. The plan prints a `WARNING` for each repo where an outside person opened a pull request before. The audit leaves bots out of that count.

```bash
gh api --method PATCH repos/OWNER/REPO -f pull_request_creation_policy=collaborators_only   # apply
gh api --method PATCH repos/OWNER/REPO -f pull_request_creation_policy=all                  # undo
```

### `fork_approval`: approve workflow runs from all outside contributors

Why it matters: the GitHub default asks for approval only from first-time contributors. A person with one merged typo fix can then run code in your Actions. With this setting, a maintainer approves every fork pull request run from someone outside the repo.

Cost: you click **Approve and run** on each outside pull request before its checks start.

```bash
gh api --method PUT repos/OWNER/REPO/actions/permissions/fork-pr-contributor-approval -f approval_policy=all_external_contributors   # apply
gh api --method PUT repos/OWNER/REPO/actions/permissions/fork-pr-contributor-approval -f approval_policy=first_time_contributors    # undo
```

### `private_vuln_reporting`: private vulnerability reporting

Why it matters: without it, a researcher who finds a hole must open a public issue or find your email. With it, the researcher sends a private advisory that only maintainers see.

Cost: none, beyond the reports you then get.

```bash
gh api --method PUT    repos/OWNER/REPO/private-vulnerability-reporting   # apply
gh api --method DELETE repos/OWNER/REPO/private-vulnerability-reporting   # undo
```

### `vulnerability_alerts` and `security_fixes`: Dependabot alerts and security updates

Why it matters: alerts tell you when a dependency has a known vulnerability. Security updates open the pull request that fixes it. Security updates need alerts, so the script turns alerts on first.

Cost: alert email, and Dependabot pull requests to review.

```bash
gh api --method PUT    repos/OWNER/REPO/vulnerability-alerts         # apply, alerts first
gh api --method PUT    repos/OWNER/REPO/automated-security-fixes
gh api --method DELETE repos/OWNER/REPO/automated-security-fixes     # undo, updates first
gh api --method DELETE repos/OWNER/REPO/vulnerability-alerts
```

### `workflow_token`: read-only `GITHUB_TOKEN`

Why it matters: every workflow run gets a `GITHUB_TOKEN`. With write access, a compromised step can push code, change releases, or approve its own pull request. Read-only by default means each workflow must ask for write access in a `permissions:` block.

Cost: a workflow that writes and has no `permissions:` block fails until you add the block.

```bash
gh api --method PUT repos/OWNER/REPO/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false    # apply
gh api --method PUT repos/OWNER/REPO/actions/permissions/workflow \
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true    # undo
```

### `ruleset_main`: protect the default branch

Why it matters: a force push or a deletion of the default branch rewrites history that others build on. The ruleset `Protect main` targets `~DEFAULT_BRANCH` with the rules `deletion` and `non_fast_forward`. It has no bypass, so admins cannot force push either.

Cost: no force push to the default branch, even to clean up a mistake. Revert the commit instead.

### `ruleset_tags`: protect release tags

Why it matters: a moved tag makes `@v1` point to code you never released. Anyone who pins your action or package to the tag then runs that code. The ruleset `Protect release tags` targets `refs/tags/v*` with the rules `creation`, `update`, `deletion` and `non_fast_forward`. Repository role 5, the admin role, can always bypass it, so you can still cut a release.

Cost: only admins can create a `v*` tag. Nobody can move or delete one without admin rights.

The script never makes a second ruleset with the same name. If a ruleset with that name exists but differs, the script updates it. The update keeps the extra rules, ref patterns and bypass actors in it. The audit shows which part differs, such as `differs(rules,bypass)`. It adds `x2` when two rulesets share the name.

```bash
gh api repos/OWNER/REPO/rulesets --jq '.[] | "\(.id) \(.name)"'   # find the ruleset id
gh api --method DELETE repos/OWNER/REPO/rulesets/RULESET_ID          # undo
```

### `secret_scanning` and `push_protection`: secret scanning

Why it matters: secret scanning finds tokens that someone committed. Push protection blocks a push that holds a token, before the token is public.

Cost: a push with a false positive stops until the person who pushed marks it as safe.

```bash
gh api --method PATCH repos/OWNER/REPO -f 'security_and_analysis[secret_scanning][status]=enabled'                   # apply
gh api --method PATCH repos/OWNER/REPO -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
gh api --method PATCH repos/OWNER/REPO -f 'security_and_analysis[secret_scanning_push_protection][status]=disabled'  # undo
gh api --method PATCH repos/OWNER/REPO -f 'security_and_analysis[secret_scanning][status]=disabled'
```

## Report-only items

The script reports these items and never changes them. They need a human, because the fix is a file in the repo or a decision about people.

| Column | Values | Meaning |
|---|---|---|
| `linters` | `none`, `ok`, `missing` | `missing` means `.github/workflows` has workflows, but none of them runs `actionlint` or `zizmor`. These tools catch workflow injection and unsafe triggers. |
| `security.md` | `yes`, `no` | `no` means GitHub finds no security policy, such as a `SECURITY.md`, for the repo. |
| `outside-prs` | a count | The number of people without write access who opened pull requests. The JSON output lists their logins. It scans the newest 500 pull requests. Pass `--pr-pages` to scan more. |

## Requests and limits

- The script reads up to 6 repos at once. Change the number with `--jobs`, up to 16.
- The script waits and retries when GitHub returns a rate limit. It gives up when the reset is more than 5 minutes away.
- It retries a read or an idempotent write that gets no response, such as a network timeout. After the retries, it reports the error for that repo and goes on.
- It never resends a `POST` that gets no response, because the first one can have reached GitHub. The only `POST` creates a ruleset. A lost reply prints `FAILED`, and the next run finds the ruleset if it exists and creates nothing.
- It reads a 404 on a feature as `n/a`. The exception is Dependabot alerts, where GitHub answers 404 to mean "off".
- It passes every argument to `gh` as a list, never through a shell. It prints values and API messages only, never headers or tokens.

## Rules

- Never pass `--apply` before the user has seen the plan and said yes.
- Never apply `pr_policy` to a repo with a `WARNING` line until the user accepts it for that repo. Otherwise pass `--skip pr_policy`.
- Never change a report-only item through this skill.
