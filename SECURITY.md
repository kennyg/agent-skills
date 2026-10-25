# Security policy

People install these skills into their own AI coding agents, such as Claude
Code, GitHub Copilot, Cursor, and OpenCode. An agent follows a skill's
instructions and runs its bundled scripts with the user's permissions. A
tampered or unsafe skill is therefore a supply-chain risk for every user who
installs it.

## Report a vulnerability

Report security problems privately through GitHub private vulnerability
reporting:

1. Open the [security advisories page for this repo](https://github.com/kennyg/agent-skills/security/advisories/new).
2. Describe the problem, the affected skill or script, and the steps to
   reproduce it.
3. Submit the report.

You can also reach the form from the **Security** tab of the repo. Select
**Report a vulnerability**.

Do not open a public issue, discussion, or pull request for a security
problem. A public report shows the problem to attackers before a fix exists.

## Supported versions

Only the latest release tag gets security fixes. See the
[release tags on GitHub](https://github.com/kennyg/agent-skills/tags) for the
current list.

| Version | Supported |
|---------|-----------|
| Latest release tag | Yes |
| Older release tags | No |
| Unreleased commits on `main` | Fixes land here first, then ship in the next tag |

If you use an older tag, update to the latest tag to get a fix.

## Scope

A vulnerability here is a skill or bundled script that can harm the user who
installs it. The following problems are in scope:

- A skill or script runs commands that the user did not ask for.
- A skill or script reads secrets, such as tokens, keys, or credential files,
  that its task does not need.
- A skill or script sends data to a network service that the user did not ask
  for.
- A skill's instructions contain prompt injection. For example, the
  instructions tell the agent to ignore the user, hide its actions, or widen
  its own permissions.
- A script executes untrusted input. For example, a script passes file
  contents, web content, or user text to a shell, `eval`, or an interpreter
  without validation.
- A script writes or deletes files outside the paths that its task needs.
- A release tag or file in this repo differs from what the maintainer
  published.

The following problems are out of scope:

- Bugs in the agents themselves, such as Claude Code, Copilot, Cursor, or
  OpenCode. Report those to the agent's vendor.
- Bugs in third-party tools that a skill calls, such as `gh`, `hk`, or `mise`.
  Report those to the tool's project.
- A skill that gives wrong or out-of-date advice but does no harm by itself.
  Open a normal issue for that.
- Problems that need an attacker who already controls the user's machine or
  agent configuration.

## What to expect after a report

This repo has one maintainer, so there is no fixed response time. After you
report a problem, you can expect the following:

1. The maintainer acknowledges the report.
2. The maintainer confirms the problem or explains why it is not a
   vulnerability.
3. For a confirmed problem, the maintainer releases a fix in a new tag and
   publishes a GitHub security advisory. The advisory credits you, unless you
   ask to stay anonymous.

Please keep the problem private until the advisory is public.

## Install skills safely

A skill can run code on your machine through your agent. Use these steps to
lower the risk:

- Pin a release tag. Do not install from `main`, because `main` can change
  at any time. For example, these commands find the latest release tag, clone
  it, and install one skill:

  ```bash
  repo=https://github.com/kennyg/agent-skills.git
  tag=$(git ls-remote --tags --refs --sort=-v:refname "$repo" | head -n 1 | sed 's|.*refs/tags/||')
  git clone --depth 1 --branch "$tag" "$repo"
  cp -r agent-skills/skills/github-gist ~/.claude/skills/
  ```

- Read the skill before you use it. Read its `SKILL.md` and every script in
  its folder, such as files in `scripts/`. Look for network calls, secret
  reads, and shell commands that you do not expect.
- Check the release tag. Compare the tag that you installed with the
  [release tags on GitHub](https://github.com/kennyg/agent-skills/tags).
  Record the commit SHA of the tag, for example with
  `git -C agent-skills rev-parse "$tag^{commit}"`. If the SHA for a tag
  changes later, treat the tag as suspect and report it.
- Install only the skills that you need, and remove skills that you no longer
  use.
