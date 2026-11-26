#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
migrate.py — move a Ghostty theme selection to Rex, the Superlogical terminal.

    migrate.py [CONFIG ...] [--json]            # dry run (default): report, change nothing
    migrate.py [CONFIG ...] --write [--out DIR] # also write Ghostty-format palette files
    migrate.py [CONFIG ...] --apply [--out DIR] # write them, import them into Rex.app,
                                                # and choose them for Light Mode and Dark Mode

With no CONFIG, the script reads Ghostty's usual config files, in the order
Ghostty loads them. It follows `config-file` includes, resolves `theme` names
to palette files, and applies inline colors on top of the theme, as Ghostty does.

--apply works only through Rex.app's own actions (`client.theme.import` and
`client.setting.themes.<light|dark>.palette`), sent with the `rex` CLI. It
never writes Rex's private settings. It reads them, read-only, to find
existing custom themes and the current selection, so it can back them up.

Exit status: 0 when every step worked, 1 when something could not be resolved
or Rex needs a manual step, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REX_DOMAIN = "com.superlogical.rex"
TESTED_REX = "0.1.0"
COLOR_KEYS = (
    "background",
    "foreground",
    "cursor-color",
    "cursor-text",
    "selection-background",
    "selection-foreground",
)
APPEARANCES = ("light", "dark")
# Relative luminance of middle grey (CIE L* = 50).
LIGHT_LUMINANCE = 0.184
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
SHORT_HEX = re.compile(r"^#?([0-9a-fA-F]{3})$")


# --------------------------------------------------------------------------- #
# Ghostty config
# --------------------------------------------------------------------------- #


@dataclass
class Setting:
    key: str
    value: str
    file: Path
    line: int

    def where(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Loaded:
    files: list[Path] = field(default_factory=list)
    settings: list[Setting] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse_lines(path: Path, text: str) -> list[Setting]:
    """Parse Ghostty's `key = value` format. A comment is a whole line that starts with #."""
    out = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.append(Setting(key.strip(), unquote(value), path, number))
    return out


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def xdg_config() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else home() / ".config"


def app_support_ghostty() -> Path:
    return home() / "Library" / "Application Support" / "com.mitchellh.ghostty"


def default_config_paths() -> list[Path]:
    """Ghostty's config files, in the order Ghostty loads them. A later file wins."""
    dirs = [xdg_config() / "ghostty"]
    if sys.platform == "darwin" or os.environ.get("GHOSTTY_MIGRATE_MACOS"):
        dirs.append(app_support_ghostty())
    return [d / name for d in dirs for name in ("config", "config.ghostty")]


def backup_hints() -> list[Path]:
    dirs = [xdg_config() / "ghostty", app_support_ghostty()]
    found = []
    for d in dirs:
        if d.is_dir():
            found += sorted(p for p in d.iterdir() if p.is_file() and ".bak" in p.name)
    return found


def load_config(paths: list[Path], explicit: bool) -> Loaded:
    """Load each file, then its `config-file` includes after it, as Ghostty does."""
    loaded = Loaded()
    seen: set[Path] = set()

    def load(path: Path, optional: bool, chain: tuple[Path, ...]) -> None:
        path = path.expanduser()
        real = path.resolve()
        if real in chain:
            loaded.problems.append(f"include cycle: {path} includes itself through {chain[-1]}; skipped")
            return
        if real in seen:
            return
        if not path.is_file():
            if not optional:
                loaded.problems.append(f"config file not found: {path}")
            return
        seen.add(real)
        loaded.files.append(path)
        includes = []
        for s in parse_lines(path, path.read_text(errors="replace")):
            if s.key == "config-file":
                includes.append(s)
            else:
                loaded.settings.append(s)
        for inc in includes:
            value = inc.value
            optional_inc = value.startswith("?")
            target = Path(unquote(value[1:] if optional_inc else value)).expanduser()
            if not target.is_absolute():
                target = path.parent / target
            load(target, optional_inc, (*chain, real))

    for p in paths:
        load(p, optional=not explicit, chain=())
    if not loaded.files:
        loaded.problems.append("no Ghostty config file found")
    return loaded


# --------------------------------------------------------------------------- #
# Colors and themes
# --------------------------------------------------------------------------- #


def norm_color(value: str) -> str | None:
    value = value.strip()
    m = HEX.match(value)
    if m:
        return "#" + m.group(1).lower()
    m = SHORT_HEX.match(value)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1)).lower()
    return None


@dataclass
class Colors:
    palette: dict[int, str] = field(default_factory=dict)
    named: dict[str, str] = field(default_factory=dict)
    unusable: list[str] = field(default_factory=list)

    def apply(self, s: Setting) -> bool:
        """Take one color setting. Return False when the key is not a color this script moves."""
        if s.key == "palette":
            index, sep, color = s.value.partition("=")
            if not sep or not index.strip().isdigit() or not 0 <= int(index) <= 255:
                self.unusable.append(f"{s.where()}: palette = {s.value} (not N=COLOR)")
                return True
            c = norm_color(color)
            if c is None:
                self.unusable.append(f"{s.where()}: palette = {s.value} (only hex colors are migrated)")
            else:
                self.palette[int(index)] = c
            return True
        if s.key in COLOR_KEYS:
            c = norm_color(s.value)
            if c is None:
                self.unusable.append(f"{s.where()}: {s.key} = {s.value} (only hex colors are migrated)")
            else:
                self.named[s.key] = c
            return True
        return False

    def merged(self, over: Colors) -> Colors:
        return Colors({**self.palette, **over.palette}, {**self.named, **over.named}, self.unusable + over.unusable)

    def empty(self) -> bool:
        return not self.palette and not self.named

    def missing(self) -> list[str]:
        miss = [f"palette {i}" for i in range(16) if i not in self.palette]
        miss += [k for k in ("background", "foreground") if k not in self.named]
        return miss

    def to_ghostty(self, header: str) -> str:
        lines = [f"# {line}" for line in header.splitlines()]
        lines += [f"palette = {i}={c}" for i, c in sorted(self.palette.items())]
        lines += [f"{k} = {self.named[k]}" for k in COLOR_KEYS if k in self.named]
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        return {"palette": {str(i): c for i, c in sorted(self.palette.items())}, **self.named}


def parse_theme_spec(value: str) -> dict[str, str]:
    """`Name` -> both appearances; `light:A,dark:B` -> one per appearance."""
    parts = [p.strip() for p in value.split(",")]
    pairs = {}
    for p in parts:
        k, sep, v = p.partition(":")
        if sep and k.strip().lower() in APPEARANCES:
            pairs[k.strip().lower()] = unquote(v)
    if pairs and len(pairs) == len(parts):
        return pairs
    name = unquote(value)
    return {"light": name, "dark": name}


def theme_dirs(extra: list[Path]) -> list[Path]:
    """Where Ghostty looks for a theme name: the user's folder, then its bundled themes."""
    dirs = list(extra)
    dirs.append(xdg_config() / "ghostty" / "themes")
    dirs.append(app_support_ghostty() / "themes")
    res = os.environ.get("GHOSTTY_RESOURCES_DIR")
    if res:
        dirs.append(Path(res) / "themes")
    for apps in (Path("/Applications"), home() / "Applications"):
        dirs.append(apps / "Ghostty.app" / "Contents" / "Resources" / "ghostty" / "themes")
    dirs += [Path("/usr/share/ghostty/themes"), Path("/usr/local/share/ghostty/themes")]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def resolve_theme(name: str, dirs: list[Path]) -> Path | None:
    p = Path(name).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    for d in dirs:
        candidate = d / name
        if candidate.is_file():
            return candidate
    return None


def read_theme(path: Path) -> Colors:
    colors = Colors()
    for s in parse_lines(path, path.read_text(errors="replace")):
        colors.apply(s)
    return colors


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


@dataclass
class RexTheme:
    name: str
    appearances: list[str]
    source: str
    colors: Colors
    file_name: str

    def missing(self) -> list[str]:
        return self.colors.missing()

    def predicted(self) -> str:
        """The appearance Rex is likely to give the theme, from how bright its background is.

        Rex classes every imported theme as light or dark, and a Light Mode or Dark Mode
        slot accepts only a theme of its own class. Rex's built-in dark themes have a
        background luminance of 0.003 to 0.024 and its light themes 0.876 to 1.0, so
        middle grey is the cut-off. --apply reads the real class back after the import.
        """
        bg = self.colors.named.get("background")
        if not bg:
            return "dark"
        r, g, b = (int(bg[i : i + 2], 16) / 255 for i in (1, 3, 5))

        def linear(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        luminance = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
        return "light" if luminance > LIGHT_LUMINANCE else "dark"


@dataclass
class Plan:
    config_files: list[Path]
    theme_setting: Setting | None
    spec: dict[str, str]
    resolved: dict[str, str | None]
    inline: Colors
    themes: list[RexTheme]
    not_migrated: list[Setting]
    problems: list[str]
    searched: list[Path]


def safe_file_name(name: str) -> str:
    return re.sub(r"[/\\:\x00]", "-", name).strip() or "Ghostty"


def build_plan(loaded: Loaded, extra_theme_dirs: list[Path]) -> Plan:
    problems = list(loaded.problems)
    inline = Colors()
    theme_setting = None
    not_migrated = []
    for s in loaded.settings:
        if s.key == "theme":
            theme_setting = s
        elif not inline.apply(s):
            not_migrated.append(s)

    dirs = theme_dirs(extra_theme_dirs)
    spec = parse_theme_spec(theme_setting.value) if theme_setting else {}
    resolved: dict[str, str | None] = {}
    base: dict[str, Colors] = {}
    missing: set[str] = set()
    for appearance in APPEARANCES:
        name = spec.get(appearance)
        if not name:
            continue
        path = resolve_theme(name, dirs)
        resolved[appearance] = str(path) if path else None
        if path:
            base[appearance] = read_theme(path)
        elif name not in missing:
            missing.add(name)
            problems.append(
                f"theme not found: '{name}' (from {theme_setting.where()}). Ghostty may be uninstalled; "
                "copy the theme file into a folder and pass it with --themes-dir"
            )

    custom = "" if inline.empty() else " (custom)"
    themes: list[RexTheme] = []
    if spec:
        by_name: dict[str, list[str]] = {}
        for appearance in APPEARANCES:
            if appearance in base:
                by_name.setdefault(spec[appearance], []).append(appearance)
        for name, apps in by_name.items():
            colors = base[apps[0]].merged(inline)
            rex_name = name + custom
            source = f"Ghostty theme '{name}'" + (" with inline colors" if custom else "")
            themes.append(RexTheme(rex_name, apps, source, colors, safe_file_name(rex_name)))
        # A theme that did not resolve still has inline colors: report, do not guess.
    elif not inline.empty():
        themes.append(RexTheme("Ghostty", list(APPEARANCES), "inline Ghostty colors", inline, "Ghostty"))
    else:
        problems.append("the Ghostty config sets no theme and no colors; nothing to migrate")

    return Plan(
        config_files=loaded.files,
        theme_setting=theme_setting,
        spec=spec,
        resolved=resolved,
        inline=inline,
        themes=themes,
        not_migrated=not_migrated,
        problems=problems,
        searched=dirs,
    )


# --------------------------------------------------------------------------- #
# Rex
# --------------------------------------------------------------------------- #


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def read_rex_defaults() -> dict | None:
    """Read Rex's settings, read-only. Return None when they cannot be read."""
    if not shutil.which("defaults"):
        return None
    proc = subprocess.run(["defaults", "export", REX_DOMAIN, "-"], capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return plistlib.loads(proc.stdout)
    except Exception:
        return None


@dataclass
class Custom:
    id: str
    name: str
    appearance: str | None


def custom_themes(prefs: dict | None) -> dict[str, Custom]:
    """Map each custom theme's lower-case name to its entry.

    Rex 0.1.0 keeps custom themes as a JSON list in `Workspace.customThemes`, each
    with `id`, `name` and `appearance`. The storage is private and may change, so
    this reads it only, and returns nothing for a shape it does not know.
    """
    if not prefs:
        return {}
    raw = prefs.get("Workspace.customThemes")
    if isinstance(raw, bytes | str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    found: dict[str, Custom] = {}
    for node in raw if isinstance(raw, list) else []:
        if isinstance(node, dict) and isinstance(node.get("id"), str) and isinstance(node.get("name"), str):
            appearance = node.get("appearance") if node.get("appearance") in APPEARANCES else None
            found[node["name"].lower()] = Custom(node["id"], node["name"], appearance)
    return found


def selection(prefs: dict | None) -> dict[str, str | None]:
    prefs = prefs or {}
    return {a: prefs.get(f"Workspace.{a}ThemeID") for a in APPEARANCES}


def find_app_client(rex: str) -> tuple[str | None, str]:
    """Return (client ID, version) of the connected Rex.app, or (None, reason)."""
    if not shutil.which(rex) and not Path(rex).is_file():
        return None, f"the `{rex}` CLI is not on PATH"
    proc = run([rex, "client", "ls", "--json"])
    if proc.returncode != 0:
        return None, f"`{rex} client ls` failed: {proc.stderr.strip() or proc.stdout.strip()}"
    try:
        clients = json.loads(proc.stdout).get("clients", [])
    except ValueError:
        return None, f"`{rex} client ls --json` printed no JSON"
    for c in clients:
        info = c.get("info") or {}
        if info.get("kind") == "app" and c.get("connection_state", "connected") == "connected":
            return c["client_id"], info.get("version", "?")
    return None, "Rex.app is not running or not connected to its server"


def rex_do(rex: str, client: str, action: str, **args: str) -> tuple[bool, str]:
    cmd = [rex, "-C", client, "do", action, *[f"{k}={v}" for k, v in args.items()]]
    proc = run(cmd)
    message = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
    return proc.returncode == 0, message[-1] if message else ""


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def default_out() -> Path:
    return xdg_config() / "rex" / "ghostty-themes"


def write_file(path: Path, content: str, stamp: str) -> str:
    """Write content, and back up a different file at the same path first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(errors="replace") == content:
            return "unchanged"
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        shutil.copy2(path, backup)
        path.write_text(content)
        return f"replaced; old file saved as {backup}"
    path.write_text(content)
    return "written"


def header_for(theme: RexTheme) -> str:
    return (
        f"{theme.name}\n"
        f"Made by the ghostty-rex-theme skill from {theme.source}.\n"
        "Import it in Rex: Settings > Themes > Import Theme."
    )


def plan_json(plan: Plan, prefs: dict | None) -> dict:
    customs = custom_themes(prefs)
    targets, refused = slot_plan(plan, customs)
    return {
        "config_files": [str(p) for p in plan.config_files],
        "theme_setting": (
            {"value": plan.theme_setting.value, "at": plan.theme_setting.where()} if plan.theme_setting else None
        ),
        "theme_per_appearance": plan.spec,
        "resolved_theme_files": plan.resolved,
        "inline_colors": plan.inline.to_json(),
        "rex_themes": [
            {
                "name": t.name,
                "appearances": t.appearances,
                "source": t.source,
                "file_name": t.file_name,
                "colors": t.colors.to_json(),
                "missing": t.missing(),
                "rex_class": rex_class(t, customs),
            }
            for t in plan.themes
        ],
        "rex_selection_now": selection(prefs),
        "rex_selection_planned": {slot: t.name for slot, t in targets.items()},
        "rex_refused": [{"theme": t.name, "slot": slot, "rex_class": kind} for t, slot, kind in refused],
        "rex_custom_themes_now": sorted(c.name for c in custom_themes(prefs).values()),
        "not_migrated": [{"key": s.key, "value": s.value, "at": s.where()} for s in plan.not_migrated],
        "unusable_colors": [u for t in plan.themes for u in t.colors.unusable] or plan.inline.unusable,
        "problems": plan.problems,
    }


def swatch(color: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return ""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m "


def print_report(plan: Plan, prefs: dict | None, out: Path) -> None:
    p = print
    p("Ghostty")
    if plan.config_files:
        for f in plan.config_files:
            p(f"  config: {f}")
    else:
        p("  config: none found")
        hints = backup_hints()
        if hints:
            p("  These backup files exist. Pass one as an argument to migrate it:")
            for h in hints:
                p(f"    {h}")
    if plan.theme_setting:
        p(f"  theme: {plan.theme_setting.value}   ({plan.theme_setting.where()})")
        for a in APPEARANCES:
            if a in plan.spec:
                path = plan.resolved.get(a)
                p(f"    {a:5} -> {plan.spec[a]}: {path or 'NOT FOUND'}")
    else:
        p("  theme: not set")
    if not plan.inline.empty():
        p("  inline colors (override the theme):")
        for i, c in sorted(plan.inline.palette.items()):
            p(f"    palette {i} = {swatch(c)}{c}")
        for k, c in plan.inline.named.items():
            p(f"    {k} = {swatch(c)}{c}")

    p("")
    p("Resolved colors")
    if not plan.themes:
        p("  none")
    for t in plan.themes:
        p(f"  {t.name}  ({t.source})")
        row = "".join(swatch(t.colors.palette[i]) for i in range(16) if i in t.colors.palette)
        if row:
            p(f"    {row}")
        for i, c in sorted(t.colors.palette.items()):
            if i < 16:
                p(f"    palette {i:2} = {c}")
        extended = sum(1 for i in t.colors.palette if i >= 16)
        if extended:
            p(f"    palette 16-255: {extended} colors")
        for k in COLOR_KEYS:
            if k in t.colors.named:
                p(f"    {k} = {swatch(t.colors.named[k])}{t.colors.named[k]}")
        if t.missing():
            p(f"    not set, so Rex uses its defaults: {', '.join(t.missing())}")

    p("")
    p("Rex")
    now = selection(prefs)
    customs = custom_themes(prefs)
    if prefs is None:
        p("  current settings: could not read (Rex is not installed, or this is not macOS)")
    else:
        p(f"  Light Mode theme now: {now['light'] or 'default'}")
        p(f"  Dark Mode theme now:  {now['dark'] or 'default'}")
    for t in plan.themes:
        known = customs.get(t.name.lower())
        state = "already a custom theme" if known else f"import {out / t.file_name}"
        kind = rex_class(t, customs)
        how = "Rex classes it as" if known else "Rex will likely class it as"
        p(f"  {t.name}: {state}. {how} {kind}.")
    targets, refused = slot_plan(plan, customs)
    for slot in APPEARANCES:
        label = f"{slot.capitalize()} Mode"
        if slot in targets:
            p(f"  {label}: {now.get(slot) or 'default'} -> {targets[slot].name}")
        else:
            p(f"  {label}: stays {now.get(slot) or 'default'}")
    for t, slot, kind in refused:
        p(
            f"  NOTE: Ghostty uses '{t.name}' in {slot} mode, but Rex accepts only {slot} themes for "
            f"{slot.capitalize()} Mode, and '{t.name}' is {kind}."
        )

    p("")
    p("Not migrated (Rex has no setting for these here; migrate them later)")
    if plan.not_migrated:
        for s in plan.not_migrated:
            p(f"  {s.key} = {s.value}   ({s.where()})")
    else:
        p("  nothing")
    unusable = [u for t in plan.themes for u in t.colors.unusable] or plan.inline.unusable
    for u in unusable:
        p(f"  {u}")
    if any(s.key == "keybind" for s in plan.not_migrated):
        p("  Rex.app can migrate keybind lines itself; see SKILL.md.")

    if plan.problems:
        p("")
        p("Problems")
        for prob in plan.problems:
            p(f"  {prob}")
        if any(prob.startswith("theme not found") for prob in plan.problems):
            p("  Searched these theme folders:")
            for d in plan.searched:
                p(f"    {d}")


def manual_steps(plan: Plan, out: Path, customs: dict[str, Custom]) -> list[str]:
    steps = ["In Rex, open Settings > Themes."]
    for t in plan.themes:
        steps.append(f"Choose Import Theme, and pick {out / t.file_name}.")
    targets, _ = slot_plan(plan, customs)
    for slot, t in targets.items():
        steps.append(f"Under {slot.capitalize()} Mode, choose '{t.name}'.")
    return steps


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def rex_class(theme: RexTheme, customs: dict[str, Custom]) -> str:
    known = customs.get(theme.name.lower())
    return (known.appearance if known else None) or theme.predicted()


def slot_plan(plan: Plan, customs: dict[str, Custom]) -> tuple[dict[str, RexTheme], list[tuple[RexTheme, str, str]]]:
    """Choose a theme for each Rex slot. A slot takes only a theme of its own class."""
    targets: dict[str, RexTheme] = {}
    refused: list[tuple[RexTheme, str, str]] = []
    for t in plan.themes:
        kind = rex_class(t, customs)
        for slot in t.appearances:
            if slot == kind:
                targets[slot] = t
            elif len(t.appearances) == 1:
                # A pair asked for this slot on purpose. A single theme fills only its own slot.
                refused.append((t, slot, kind))
    return targets, refused


def apply_to_rex(plan: Plan, prefs: dict | None, out: Path, rex: str, stamp: str) -> bool:
    client, info = find_app_client(rex)
    if client is None:
        print(f"Rex: cannot apply automatically: {info}.")
        return False
    print(f"Rex: using Rex.app {info} (client {client}). Tested with Rex {TESTED_REX}.")
    before = selection(prefs)
    backup = out / f"rex-theme-selection.bak-{stamp}.json"
    undo = [
        f"{rex} -C {client} do client.setting.themes.{a}.palette value={before[a]}" for a in APPEARANCES if before[a]
    ]
    backup.write_text(json.dumps({"selection": before, "undo": undo}, indent=2) + "\n")
    print(f"Rex: saved the current Light Mode and Dark Mode choice in {backup}")

    customs = custom_themes(prefs)
    for t in plan.themes:
        if t.name.lower() in customs:
            print(f"Rex: '{t.name}' is already a custom theme; not imported again.")
            continue
        done, msg = rex_do(rex, client, "client.theme.import", path=str(out / t.file_name))
        print(f"Rex: import '{t.name}': {'ok' if done else 'FAILED: ' + msg}")
        if not done:
            if "Remote Control" in msg:
                print("Rex: turn on Remote Control in Rex Settings > General, then run --apply again.")
            return False
    time.sleep(0.5)
    customs = custom_themes(read_rex_defaults()) or customs

    # Rex puts an imported theme in the slot of its class at once. Choose every slot
    # explicitly: the planned theme, or the old choice for a slot the plan leaves alone.
    ok = True
    targets, refused = slot_plan(plan, customs)
    want: dict[str, str | None] = {}
    for slot in APPEARANCES:
        if slot in targets:
            t = targets[slot]
            known = customs.get(t.name.lower())
            value, label = (known.id if known else t.name), t.name
        else:
            value = label = before[slot]
        want[slot] = value
        if not value:
            continue
        done, msg = rex_do(rex, client, f"client.setting.themes.{slot}.palette", value=value)
        print(f"Rex: {slot.capitalize()} Mode -> '{label}': {'ok' if done else 'FAILED: ' + msg}")
        ok &= done
    for t, slot, kind in refused:
        print(f"Rex: NOT DONE: '{t.name}' is {kind}, and Rex accepts only {slot} themes for {slot.capitalize()} Mode.")
        ok = False

    time.sleep(0.5)
    after = selection(read_rex_defaults())
    for slot in APPEARANCES:
        if want[slot] and after[slot] != want[slot]:
            print(f"Rex: check FAILED: {slot.capitalize()} Mode is '{after[slot]}', expected '{want[slot]}'.")
            ok = False
    print("")
    print("Undo: choose the old themes again with")
    for u in undo or ["(Rex used its default themes; choose them in Settings > Themes)"]:
        print(f"  {u}")
    print("Then delete the imported custom themes in Settings > Themes if you do not want them.")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move a Ghostty theme selection to Rex.")
    ap.add_argument("config", nargs="*", type=Path, help="Ghostty config file(s); default: Ghostty's usual files")
    ap.add_argument("--themes-dir", action="append", type=Path, default=[], help="extra folder of Ghostty themes")
    ap.add_argument("--out", type=Path, help="folder for the palette files (default: $XDG_CONFIG_HOME/rex/...)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the palette files only")
    mode.add_argument("--apply", action="store_true", help="write the files, import them and choose them in Rex")
    ap.add_argument("--rex", default="rex", help="the rex CLI (default: rex on PATH)")
    ap.add_argument("--json", action="store_true", help="print the dry-run report as JSON")
    args = ap.parse_args(argv)
    if args.json and (args.write or args.apply):
        ap.error("--json is for the dry run only")

    explicit = bool(args.config)
    loaded = load_config(args.config or default_config_paths(), explicit)
    plan = build_plan(loaded, args.themes_dir)
    prefs = read_rex_defaults()
    out = (args.out or default_out()).expanduser()

    if args.json:
        print(json.dumps(plan_json(plan, prefs), indent=2))
        return 1 if plan.problems else 0

    print_report(plan, prefs, out)
    print("")
    if not plan.themes:
        print("Nothing to do.")
        return 1
    if not (args.write or args.apply):
        print("Dry run: nothing changed. Pass --write to write the palette files, or --apply to also set them in Rex.")
        return 1 if plan.problems else 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for t in plan.themes:
        state = write_file(out / t.file_name, t.colors.to_ghostty(header_for(t)), stamp)
        print(f"Wrote {out / t.file_name}: {state}")
    ok = not plan.problems
    if args.apply:
        ok = apply_to_rex(plan, prefs, out, args.rex, stamp) and ok
        if not ok:
            print("")
            print("To finish by hand:")
            for i, step in enumerate(manual_steps(plan, out, custom_themes(read_rex_defaults())), 1):
                print(f"  {i}. {step}")
    else:
        print("")
        print("Next steps:")
        for i, step in enumerate(manual_steps(plan, out, custom_themes(read_rex_defaults())), 1):
            print(f"  {i}. {step}")
        print(f"To undo, delete the files in {out}.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
