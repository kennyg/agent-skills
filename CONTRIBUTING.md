# Contributing

## Set up

Run `mise install`. It installs the tools that `mise.toml` pins: `hk`, `uv`, Python, `ruff` and the linters.

Run `mise run check` to lint the repo. Run `mise run fix` to fix what the linters can fix. Both tasks call `hk`, and `hk` also runs on `git commit` and `git push`.

## Rules for skill scripts

These rules apply to every Python script in `skills/*/scripts/`. `hk` enforces them, so a commit fails when a script breaks one.

### Write each script as a `uv` script

Start each Python script with this shebang and a PEP 723 block. Add dependencies to the `dependencies` list in the file, never to a separate file.

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
```

Make each script executable with `chmod +x`. In `SKILL.md`, call the script by its path. Do not write `python3 script.py` or `uv run script.py`.

A helper module that scripts import is not a command. Name it with a leading underscore, such as `_wikilib.py`. It needs no shebang and no executable bit.

### Keep local paths out of the skill

Do not write a machine path in a skill script or in its `SKILL.md`. That includes `/Users/`, `/home/`, `~/` and `Mobile Documents`.

Take the project root from an argument. If the user gives no argument, read `$CLAUDE_PROJECT_DIR`, then use the current directory. Paths in a task brief are for testing only.

## Check the rules

| Task | What it does |
|---|---|
| `mise run check` | Runs every `hk` check on all files. |
| `mise run fix` | Runs every `hk` fixer on all files. |
| `mise run test-skills` | Runs the `unittest` suite in each `skills/*/tests` folder. |

The `hk` steps for skill scripts are `ruff`, `ruff_format`, `script-header` and `script-paths`. The last two are small scripts in `scripts/`: `check-script-header.sh` and `check-script-paths.sh`. Each one prints the files that break its rule.

## Add a skill

Put the skill in `skills/<name>/SKILL.md`. Run `mise run skills-table` to update the table in `README.md`.
