"""Tests for migrate.py with fixture Ghostty configs and themes. No test calls the real Rex.

Run with: python3 -m unittest discover -s skills/ghostty-rex-theme/tests
Each test points HOME and XDG_CONFIG_HOME at an empty temporary folder, so the
user's own Ghostty and Rex files are never read. The apply tests replace the
`rex` CLI and the Rex settings reader with a fake that records each action.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
CONFIGS = FIXTURES / "configs"
THEMES = FIXTURES / "themes"
sys.path.insert(0, str(SCRIPTS))
import migrate  # noqa: E402


class Isolated(unittest.TestCase):
    """Run each test with an empty HOME, so only fixtures are read."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ghostty-rex-"))
        env = {"HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp / ".config")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("GHOSTTY_RESOURCES_DIR", None)
        # No test may read the real Rex settings.
        reader = mock.patch.object(migrate, "read_rex_defaults", return_value=None)
        reader.start()
        self.addCleanup(reader.stop)

    def plan(self, *configs: str, themes: Path | None = THEMES) -> migrate.Plan:
        loaded = migrate.load_config([CONFIGS / c for c in configs], explicit=True)
        return migrate.build_plan(loaded, [themes] if themes else [])

    def main(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = migrate.main(list(argv))
        return code, buf.getvalue()


class ParseTests(unittest.TestCase):
    def test_theme_spec_single(self):
        self.assertEqual(
            migrate.parse_theme_spec('"Catppuccin Macchiato"'),
            {"light": "Catppuccin Macchiato", "dark": "Catppuccin Macchiato"},
        )

    def test_theme_spec_pair_any_order(self):
        want = {"light": "A B", "dark": "C"}
        self.assertEqual(migrate.parse_theme_spec("light:A B,dark:C"), want)
        self.assertEqual(migrate.parse_theme_spec("dark:C, light:A B"), want)

    def test_theme_name_with_colon_is_a_name(self):
        self.assertEqual(migrate.parse_theme_spec("Foo: Bar")["dark"], "Foo: Bar")

    def test_norm_color(self):
        self.assertEqual(migrate.norm_color("#AABBCC"), "#aabbcc")
        self.assertEqual(migrate.norm_color("aabbcc"), "#aabbcc")
        self.assertEqual(migrate.norm_color("#f00"), "#ff0000")
        self.assertIsNone(migrate.norm_color("red"))


class NamedThemeTests(Isolated):
    def test_named_theme_resolves_from_themes_dir(self):
        plan = self.plan("named")
        self.assertEqual(plan.problems, [])
        self.assertEqual(len(plan.themes), 1)
        theme = plan.themes[0]
        self.assertEqual(theme.name, "Fixture Dark")
        self.assertEqual(theme.appearances, ["light", "dark"])
        self.assertEqual(theme.colors.named["background"], "#101010")
        self.assertEqual(len(theme.colors.palette), 16)
        self.assertEqual(theme.missing(), [])

    def test_user_themes_folder_is_searched(self):
        user = self.tmp / ".config" / "ghostty" / "themes"
        user.mkdir(parents=True)
        (user / "Fixture Dark").write_text((THEMES / "Fixture Dark").read_text())
        plan = self.plan("named", themes=None)
        self.assertEqual(plan.resolved["dark"], str(user / "Fixture Dark"))

    def test_unmigrated_settings_are_listed(self):
        plan = self.plan("named")
        keys = [s.key for s in plan.not_migrated]
        self.assertEqual(keys, ["font-family", "background-opacity", "keybind"])
        self.assertTrue(plan.not_migrated[0].where().endswith("named:2"))

    def test_real_world_backup(self):
        plan = self.plan("real-world-macchiato")
        self.assertEqual(plan.problems, [])
        theme = plan.themes[0]
        self.assertEqual(theme.name, "Catppuccin Macchiato")
        self.assertEqual(theme.colors.named["background"], "#24273a")
        self.assertEqual(theme.colors.palette[4], "#8aadf4")
        not_migrated = {s.key: s.value for s in plan.not_migrated}
        self.assertEqual(not_migrated["font-family"], "MesloLGS NF")
        self.assertEqual(not_migrated["background-opacity"], "0.88")


class LightDarkTests(Isolated):
    def test_pair_maps_to_light_and_dark(self):
        for config in ("light-dark", "dark-light-reversed"):
            with self.subTest(config=config):
                plan = self.plan(config)
                by_name = {t.name: t.appearances for t in plan.themes}
                self.assertEqual(by_name, {"Fixture Light": ["light"], "Fixture Dark": ["dark"]})

    def test_pair_with_one_missing_theme(self):
        d = self.tmp / "cfg"
        d.write_text("theme = light:Fixture Light,dark:Gone Missing 9c1\n")
        plan = migrate.build_plan(migrate.load_config([d], explicit=True), [THEMES])
        self.assertEqual([(t.name, t.appearances) for t in plan.themes], [("Fixture Light", ["light"])])
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("Gone Missing 9c1", plan.problems[0])


class ClassTests(Isolated):
    def test_predicted_class(self):
        plan = self.plan("light-dark")
        kinds = {t.name: t.predicted() for t in plan.themes}
        self.assertEqual(kinds, {"Fixture Light": "light", "Fixture Dark": "dark"})

    def test_dry_run_shows_slots(self):
        code, out = self.main(str(CONFIGS / "named"), "--themes-dir", str(THEMES))
        self.assertEqual(code, 0)
        self.assertIn("Rex will likely class it as dark", out)


class InlineTests(Isolated):
    def test_inline_palette_without_theme(self):
        plan = self.plan("inline")
        theme = plan.themes[0]
        self.assertEqual(theme.name, "Ghostty")
        self.assertEqual(theme.colors.palette[1], "#cc6666")
        self.assertEqual(theme.colors.palette[9], "#ff0000")
        self.assertNotIn(3, theme.colors.palette)
        self.assertEqual(theme.colors.named["selection-foreground"], "#c5c8c6")
        self.assertEqual(len(theme.colors.unusable), 2)  # palette 300 and the named color "red"
        self.assertIn("palette 4", theme.missing())

    def test_inline_colors_override_theme(self):
        plan = self.plan("theme-plus-inline")
        theme = plan.themes[0]
        self.assertEqual(theme.name, "Fixture Dark (custom)")
        self.assertEqual(theme.colors.named["background"], "#000011")
        self.assertEqual(theme.colors.palette[1], "#ff0000")
        self.assertEqual(theme.colors.palette[2], "#00aa00")

    def test_ghostty_file_round_trip(self):
        theme = self.plan("theme-plus-inline").themes[0]
        path = self.tmp / "out"
        path.write_text(theme.colors.to_ghostty(migrate.header_for(theme)))
        again = migrate.read_theme(path)
        self.assertEqual(again.palette, theme.colors.palette)
        self.assertEqual(again.named, theme.colors.named)


class MissingTests(Isolated):
    def test_missing_theme_is_reported(self):
        plan = self.plan("missing", themes=None)
        self.assertEqual(plan.themes, [])
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("theme not found: 'No Such Theme Anywhere 7f3a'", plan.problems[0])
        self.assertEqual([s.key for s in plan.not_migrated], ["font-size"])

    def test_missing_theme_exit_code_and_report(self):
        code, out = self.main(str(CONFIGS / "missing"))
        self.assertEqual(code, 1)
        self.assertIn("NOT FOUND", out)
        self.assertIn("Searched these theme folders", out)

    def test_no_config_found_lists_backups(self):
        ghostty = self.tmp / ".config" / "ghostty"
        ghostty.mkdir(parents=True)
        (ghostty / "config.ghostty.bak").write_text("theme = X\n")
        code, out = self.main()
        self.assertEqual(code, 1)
        self.assertIn("config: none found", out)
        self.assertIn("config.ghostty.bak", out)

    def test_default_paths_are_read(self):
        ghostty = self.tmp / ".config" / "ghostty"
        ghostty.mkdir(parents=True)
        (ghostty / "config").write_text("theme = Fixture Dark\n")
        code, out = self.main("--themes-dir", str(THEMES))
        self.assertEqual(code, 0, out)
        self.assertIn("Fixture Dark", out)


class IncludeTests(Isolated):
    def test_includes_load_after_the_file(self):
        plan = self.plan("includes/main")
        self.assertEqual([p.name for p in plan.config_files], ["main", "colors"])
        self.assertEqual(plan.theme_setting.value, "Fixture Dark")
        self.assertEqual(plan.themes[0].name, "Fixture Dark (custom)")
        self.assertEqual(plan.themes[0].colors.named["foreground"], "#abcdef")

    def test_include_problems(self):
        plan = self.plan("includes/main")
        joined = "\n".join(plan.problems)
        self.assertIn("required-missing", joined)
        self.assertNotIn("optional-missing", joined)
        self.assertIn("include cycle", joined)


class JsonTests(Isolated):
    def test_json_report(self):
        code, out = self.main(str(CONFIGS / "light-dark"), "--themes-dir", str(THEMES), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["theme_per_appearance"], {"light": "Fixture Light", "dark": "Fixture Dark"})
        self.assertEqual(sorted(t["name"] for t in data["rex_themes"]), ["Fixture Dark", "Fixture Light"])


class WriteTests(Isolated):
    def test_dry_run_writes_nothing(self):
        out = self.tmp / "out"
        code, text = self.main(str(CONFIGS / "named"), "--themes-dir", str(THEMES), "--out", str(out))
        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertIn("Dry run: nothing changed", text)

    def test_write_and_back_up(self):
        out = self.tmp / "out"
        args = [str(CONFIGS / "named"), "--themes-dir", str(THEMES), "--out", str(out), "--write"]
        code, text = self.main(*args)
        self.assertEqual(code, 0, text)
        written = out / "Fixture Dark"
        self.assertIn("background = #101010", written.read_text())
        self.assertIn("Import Theme", text)

        code, text = self.main(*args)
        self.assertIn("unchanged", text)

        written.write_text("edited by hand\n")
        code, text = self.main(*args)
        backups = list(out.glob("Fixture Dark.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "edited by hand\n")


class FakeRex:
    """Stand-in for the rex CLI and Rex's settings, with Rex 0.1.0's behavior.

    An import classes the theme as light or dark from its background and puts it in
    that slot at once. A slot accepts only a theme of its own class, by ID or by name.
    """

    def __init__(self, remote_control=True, customs=None):
        self.remote_control = remote_control
        self.prefs = {
            "Workspace.lightThemeID": "merino-light",
            "Workspace.darkThemeID": "merino-dark",
        }
        self.themes = {"merino-light": ("Merino Light", "light"), "merino-dark": ("Merino Dark", "dark")}
        for name, (ident, kind) in (customs or {}).items():
            self.themes[ident] = (name, kind)
        self.calls: list[list[str]] = []
        self.sync()

    def sync(self):
        customs = [
            {"id": i, "name": n, "appearance": k, "palette": {}} for i, (n, k) in self.themes.items() if "custom" in i
        ]
        if customs:
            self.prefs["Workspace.customThemes"] = json.dumps(customs).encode()

    def read(self):
        return dict(self.prefs)

    def run(self, cmd):
        self.calls.append(cmd)
        if cmd[1:] == ["client", "ls", "--json"]:
            clients = [
                {"client_id": "client:cli"},
                {"client_id": "client:app", "info": {"kind": "app", "version": "0.1.0"}},
            ]
            return SimpleNamespace(returncode=0, stdout=json.dumps({"clients": clients}), stderr="")
        assert cmd[1:4] == ["-C", "client:app", "do"], cmd
        if not self.remote_control:
            msg = "Error: Rex.app is not accepting actions. Turn on Remote Control in its Settings under General."
            return SimpleNamespace(returncode=1, stdout="", stderr=msg)
        action, arg = cmd[4], cmd[5]
        _, _, value = arg.partition("=")
        if action == "client.theme.import":
            colors = migrate.read_theme(Path(value))
            kind = migrate.RexTheme("x", [], "", colors, "x").predicted()
            ident = f"custom-{len(self.themes)}"
            self.themes[ident] = (Path(value).name, kind)
            self.prefs[f"Workspace.{kind}ThemeID"] = ident
            self.sync()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        slot = action.split(".")[3]
        for ident, (name, kind) in self.themes.items():
            if value in (ident, name.lower(), name) and kind == slot:
                self.prefs[f"Workspace.{slot}ThemeID"] = ident
                return SimpleNamespace(returncode=0, stdout="", stderr="")
        msg = f'Error: "{value}" isn\'t a value {action} accepts. It takes the name of a {slot} theme.'
        return SimpleNamespace(returncode=1, stdout="", stderr=msg)


class ApplyTests(Isolated):
    def apply(self, fake: FakeRex, config="light-dark"):
        out = self.tmp / "out"
        patches = [
            mock.patch.object(migrate, "run", fake.run),
            mock.patch.object(migrate, "read_rex_defaults", fake.read),
            mock.patch.object(migrate.shutil, "which", return_value="/fake/rex"),
            mock.patch.object(migrate.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        args = [str(CONFIGS / config), "--themes-dir", str(THEMES), "--out", str(out), "--apply"]
        code, text = self.main(*args)
        return code, text, out

    def actions(self, fake):
        return [c[4:] for c in fake.calls if "do" in c]

    def test_apply_imports_and_selects(self):
        fake = FakeRex()
        code, text, out = self.apply(fake)
        self.assertEqual(code, 0, text)
        self.assertEqual(
            self.actions(fake),
            [
                ["client.theme.import", f"path={out / 'Fixture Light'}"],
                ["client.theme.import", f"path={out / 'Fixture Dark'}"],
                ["client.setting.themes.light.palette", "value=custom-2"],
                ["client.setting.themes.dark.palette", "value=custom-3"],
            ],
        )
        self.assertEqual(fake.prefs["Workspace.lightThemeID"], "custom-2")
        self.assertEqual(fake.prefs["Workspace.darkThemeID"], "custom-3")
        backup = json.loads(next(out.glob("rex-theme-selection.bak-*.json")).read_text())
        self.assertEqual(backup["selection"], {"light": "merino-light", "dark": "merino-dark"})
        self.assertIn("value=merino-dark", text)

    def test_single_dark_theme_fills_only_dark_mode(self):
        fake = FakeRex()
        code, text, _ = self.apply(fake, config="named")
        self.assertEqual(code, 0, text)
        self.assertEqual(fake.prefs["Workspace.lightThemeID"], "merino-light")
        self.assertEqual(fake.prefs["Workspace.darkThemeID"], "custom-2")
        self.assertNotIn("FAILED", text)

    def test_dark_theme_asked_for_light_mode_is_refused(self):
        cfg = self.tmp / "cfg"
        cfg.write_text("theme = light:Fixture Dark,dark:Fixture Dark 2\n")
        themes = self.tmp / "themes"
        themes.mkdir()
        (themes / "Fixture Dark").write_text((THEMES / "Fixture Dark").read_text())
        (themes / "Fixture Dark 2").write_text((THEMES / "Fixture Dark").read_text())
        fake = FakeRex()
        for p in (
            mock.patch.object(migrate, "run", fake.run),
            mock.patch.object(migrate, "read_rex_defaults", fake.read),
            mock.patch.object(migrate.shutil, "which", return_value="/fake/rex"),
            mock.patch.object(migrate.time, "sleep"),
        ):
            p.start()
            self.addCleanup(p.stop)
        code, text = self.main(str(cfg), "--themes-dir", str(themes), "--out", str(self.tmp / "out"), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("NOT DONE: 'Fixture Dark' is dark", text)
        self.assertEqual(fake.prefs["Workspace.lightThemeID"], "merino-light")
        # Importing Fixture Dark put it in Dark Mode; the plan wants Fixture Dark 2 there.
        self.assertEqual(fake.themes[fake.prefs["Workspace.darkThemeID"]][0], "Fixture Dark 2")

    def test_import_side_effect_is_undone_for_an_unplanned_slot(self):
        cfg = self.tmp / "cfg"
        cfg.write_text("theme = light:Fixture Dark\n")
        fake = FakeRex()
        for p in (
            mock.patch.object(migrate, "run", fake.run),
            mock.patch.object(migrate, "read_rex_defaults", fake.read),
            mock.patch.object(migrate.shutil, "which", return_value="/fake/rex"),
            mock.patch.object(migrate.time, "sleep"),
        ):
            p.start()
            self.addCleanup(p.stop)
        code, text = self.main(str(cfg), "--themes-dir", str(THEMES), "--out", str(self.tmp / "out"), "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(fake.prefs["Workspace.darkThemeID"], "merino-dark")
        self.assertEqual(fake.prefs["Workspace.lightThemeID"], "merino-light")

    def test_apply_does_not_import_twice(self):
        fake = FakeRex(customs={"Fixture Light": ("custom-l", "light"), "Fixture Dark": ("custom-d", "dark")})
        code, text, _ = self.apply(fake)
        self.assertEqual(code, 0, text)
        self.assertFalse(any("client.theme.import" in c for c in fake.calls))
        self.assertIn("already a custom theme", text)
        self.assertEqual(fake.prefs["Workspace.darkThemeID"], "custom-d")

    def test_apply_without_remote_control_gives_manual_steps(self):
        fake = FakeRex(remote_control=False)
        code, text, out = self.apply(fake)
        self.assertEqual(code, 1)
        self.assertIn("turn on Remote Control", text)
        self.assertIn("To finish by hand", text)
        self.assertTrue((out / "Fixture Dark").is_file())
        self.assertEqual(fake.prefs["Workspace.darkThemeID"], "merino-dark")


if __name__ == "__main__":
    unittest.main()
