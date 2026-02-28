# Obsidian CLI Quick Reference

The native Obsidian CLI ships with Obsidian itself — no plugins or API keys needed.

```bash
obsidian <command> [options]
```

Global option: `vault=<name>` — target a specific vault (defaults to active vault).

## Files

```bash
obsidian read path=<path>                              # Read note contents
obsidian create path=<path> content=<text>             # Create note
obsidian create path=<path> content=<text> overwrite   # Create or overwrite
obsidian append path=<path> content=<text>             # Append to note
obsidian prepend path=<path> content=<text>            # Prepend to note
obsidian delete path=<path> permanent                  # Delete permanently
obsidian move path=<path> to=<dest>                    # Move or rename
obsidian file path=<path>                              # Show file info
obsidian files [folder=<path>] [ext=<ext>]             # List files
```

## Daily Notes

```bash
obsidian daily:read                                    # Read today's daily note
obsidian daily:append content=<text>                   # Append to daily note
obsidian daily:prepend content=<text>                  # Prepend to daily note
obsidian daily:path                                    # Get daily note path
obsidian daily                                         # Open daily note
```

## Search

```bash
obsidian search query=<text>                           # Search vault
obsidian search query=<text> path=<folder>             # Limit to folder
obsidian search:context query=<text>                   # Search with context lines
obsidian tags [file=<name>] [counts]                   # List tags
```

## Properties

```bash
obsidian property:read name=<name> path=<path>         # Read a property
obsidian property:set name=<name> value=<v> path=<p>   # Set a property
obsidian property:remove name=<name> path=<path>       # Remove a property
obsidian properties [file=<name>]                      # List all properties
```

## Plugins & Snippets

```bash
obsidian snippet:enable name=<name>                    # Enable CSS snippet
obsidian snippet:disable name=<name>                   # Disable CSS snippet
obsidian snippets                                      # List snippets
obsidian plugin:enable id=<id>                         # Enable plugin
obsidian plugin:disable id=<id>                        # Disable plugin
obsidian plugin:reload id=<id>                         # Reload plugin
obsidian plugins                                       # List plugins
```

## Commands & UI

```bash
obsidian command id=<command-id>                       # Execute command
obsidian commands [filter=<prefix>]                    # List command IDs
obsidian open path=<path>                              # Open file in Obsidian
obsidian search:open query=<text>                      # Open search panel
```

## Vault

```bash
obsidian vault                                         # Show vault info
obsidian vaults                                        # List known vaults
obsidian folders [folder=<path>]                       # List folders
obsidian reload                                        # Reload vault
```

## Notes

- Exit code is always 0 — check if output starts with `"Error:"` to detect failures
- Use Bun's `$` shell for programmatic use: `await $\`obsidian read path=${p}\`.text()`
- Set `OBSIDIAN_VAULT` and pass `vault=${VAULT}` to target a specific vault from scripts
