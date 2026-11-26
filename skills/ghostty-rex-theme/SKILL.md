---
name: ghostty-rex-theme
description: "Move a Ghostty theme selection to Rex, the Superlogical terminal. Use when the user asks to migrate, copy, port or bring their Ghostty theme, colors or palette to Rex, or to use a Ghostty theme such as Catppuccin in Rex, including a light/dark theme pair."
license: MIT
metadata:
  author: Kenny Gatdula
  version: "1.0.0"
  tags: ghostty, rex, terminal, theme, colors, migration, macos
  compatibility: Any agentskills.io-compatible agent. Needs uv. Applying in Rex needs macOS, Rex.app and the rex CLI. Tested with Rex 0.1.0 (preview 35).
---

# Ghostty theme to Rex

Move a Ghostty theme selection to Rex. The script reads the Ghostty config, resolves the theme to its colors, and makes one Rex custom theme per Ghostty theme. A light/dark pair in Ghostty becomes the Light Mode and Dark Mode themes in Rex.

Rex is in beta. The script was tested with Rex 0.1.0 (app build `0.1.0-preview.35`). Rex can change its actions and its theme storage in a later release. Run the dry run first after each Rex update.

## When to use

- The user moves from Ghostty to Rex and wants the same colors.
- The user has only an old Ghostty config or a backup of one, and Ghostty is gone.
- The user wants the Ghostty theme of another machine, from a config file they copied.

Do not use it for Ghostty keybinds. Rex.app migrates keybinds itself. See [Settings it does not migrate](#settings-it-does-not-migrate).

## How it writes to Rex

Rex offers three ways to set colors. The script uses the most durable one.

| Path | Use | Why |
|---|---|---|
| Rex.app actions `client.theme.import` and `client.setting.themes.<light\|dark>.palette`, sent with `rex do` | Yes, with `--apply` | They are the public actions behind Settings > Themes. Rex.app stores the theme itself, so its storage format does not matter. |
| Settings > Themes > Import Theme, by hand | Yes, as the fallback | The script writes a Ghostty-format palette file and prints the exact steps. |
| Lua `set_theme` in `init.lua` | No | `set_theme` changes one terminal block, and the config file runs with no terminal. Rex's own Ghostty migration notes say to write no theme lines in `init.lua`. |
| The `com.superlogical.rex` defaults domain | Read only | Rex keeps custom themes in `Workspace.customThemes` and the choice in `Workspace.lightThemeID` and `Workspace.darkThemeID`. The format is private and undocumented. The script reads these keys to find existing themes and to back up the choice. It never writes them. |

Rex.app accepts actions only when Remote Control is on, in Rex Settings > General. If it is off, `--apply` stops and prints the manual steps. Ask the user to turn it on. Do not turn it on for them.

## Workflow

### 1. Dry run

```bash
<skill-dir>/scripts/migrate.py                         # Ghostty's usual config files
<skill-dir>/scripts/migrate.py path/to/ghostty/config  # one config file, such as a backup
<skill-dir>/scripts/migrate.py --json                  # the same report as JSON
```

With no path, the script reads these files in the order Ghostty loads them. A later file wins.

1. `$XDG_CONFIG_HOME/ghostty/config` and `config.ghostty`. Without `XDG_CONFIG_HOME`, the folder is `$HOME/.config/ghostty`.
2. On macOS, `config` and `config.ghostty` in `$HOME/Library/Application Support/com.mitchellh.ghostty`.

The script follows `config-file` includes. An include loads after the rest of its file, so its values win, as in Ghostty. A `?` before the path makes an include optional.

The dry run changes nothing. It prints four parts:

- The Ghostty config files, the `theme` line, and the theme file found for each appearance.
- The resolved colors of each Rex theme it would make.
- The current Rex Light Mode and Dark Mode themes, and what would change.
- The settings it does not migrate, each with its file and line.

If no config file exists, the report lists any `.bak` files in the Ghostty folders. Ask the user whether to migrate one of them, and pass its path.

Show the dry run to the user before you go on.

### 2. Apply

Apply only after the user approves the dry run. Pass the same paths.

```bash
<skill-dir>/scripts/migrate.py path/to/config --apply   # write the files, import them, choose them
<skill-dir>/scripts/migrate.py path/to/config --write   # write the files only
```

`--apply` does these steps:

1. It writes each palette file to `$XDG_CONFIG_HOME/rex/ghostty-themes/`. Pass `--out DIR` to use another folder. A different file at the same path is saved as `<name>.bak-<time>` first.
2. It saves the current Light Mode and Dark Mode choice in `rex-theme-selection.bak-<time>.json` in the same folder. The file also holds the undo commands.
3. It imports each theme with `client.theme.import`. A theme that Rex already has, by name, is not imported again.
4. It chooses each theme for its appearance with `client.setting.themes.<light|dark>.palette`.
5. It reads the choice back from Rex and prints `check FAILED` for each one that did not hold.

`--write` does only step 1 and prints the manual steps.

### 3. Undo

`--apply` prints the undo commands. They choose the old themes again, such as:

```bash
rex -C <client> do client.setting.themes.dark.palette value=merino-dark
```

The same commands are in the `rex-theme-selection.bak-<time>.json` file. Imported custom themes stay in Rex. Delete them in Settings > Themes if the user does not want them. To undo `--write`, delete the files it wrote.

## How Ghostty themes map to Rex

| Ghostty | Rex |
|---|---|
| `theme = Name` | One custom theme, chosen for both Light Mode and Dark Mode, because Ghostty uses it for both. |
| `theme = light:A,dark:B` | Two custom themes. `A` is the Light Mode theme and `B` is the Dark Mode theme. |
| `palette = N=#rrggbb`, `background`, `foreground`, `cursor-color`, `cursor-text`, `selection-background`, `selection-foreground` | The same keys in the palette file. Inline colors override the theme, as in Ghostty. The theme name then gets ` (custom)`. |
| Inline colors with no `theme` | One custom theme named `Ghostty`. |

A theme name resolves to a file in this order:

1. Each `--themes-dir DIR`.
2. The user's themes: `$XDG_CONFIG_HOME/ghostty/themes/`, then `themes/` in Ghostty's macOS Application Support folder.
3. `$GHOSTTY_RESOURCES_DIR/themes/`.
4. Ghostty's bundled themes: `Ghostty.app/Contents/Resources/ghostty/themes/` in `/Applications` or `$HOME/Applications`, then `/usr/share/ghostty/themes/`.

A theme can also be an absolute path. If Ghostty is uninstalled, its bundled themes are gone. The script then reports `theme not found` and lists the folders it searched. Get the theme file from another machine or from the [iTerm2-Color-Schemes](https://github.com/mbadolato/iTerm2-Color-Schemes) `ghostty` folder, put it in a folder, and pass `--themes-dir`. Inline colors still migrate without the theme.

Only hex colors migrate, as `#rrggbb`, `rrggbb` or `#rgb`. The report lists named colors such as `red` and bad palette lines as unusable. A theme without 16 palette colors, a background or a foreground lists them as `not set`. Rex then uses its own defaults for them.

## Settings it does not migrate

The report lists every other Ghostty setting with its file and line, under "Not migrated". Common ones:

| Ghostty setting | Where it goes in Rex |
|---|---|
| `keybind` | Rex.app has its own Ghostty migration for keybinds, which writes `rex.bind` lines to `init.lua`. |
| `font-family`, `font-size` | Settings > Terminal > Typography. Rex.app has the actions `client.setting.terminal.typography.font` and `client.setting.terminal.typography.size`. |
| `window-padding-x`, `window-padding-y` | The actions `client.setting.interface.pane_padding.horizontal` and `.vertical`. |
| `cursor-style-blink` | The actions under `client.setting.terminal.cursor`. |
| `background-opacity`, `window-width`, `window-height`, `cursor-style` | Rex 0.1.0 has no matching setting. |

Give the user this list, so they can move these settings later.

## Exit status

| Code | Meaning |
|---|---|
| 0 | Every step worked. |
| 1 | Something did not resolve, a check failed, or Rex needs a manual step. |
| 2 | Usage error. |

## Tests

```bash
python3 -m unittest discover -s skills/ghostty-rex-theme/tests -v
```

The fixtures cover a named theme, a light/dark pair, inline colors, a missing theme, includes with a cycle, and a copy of a real config with `theme = "Catppuccin Macchiato"`. The apply tests use a fake `rex` that changes fake Rex settings, so they never touch Rex.app.
