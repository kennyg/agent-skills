"""End-to-end tests for the wiki-ingest scripts against a fixture vault.

Run with: python3 -m unittest discover -s skills/wiki-ingest/tests
The tests call each script through its `uv` shebang, as `SKILL.md` does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURE = HERE / "fixtures" / "vault"
BETA = "Clippings/Beta Article.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VaultCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name) / "vault"
        shutil.copytree(FIXTURE, self.vault)
        for page in self.vault.rglob("*.md"):
            text = page.read_text(encoding="utf-8")
            text = re.sub(r"@HASH:(.+?)@", lambda m: sha256(self.vault / m.group(1)), text)
            page.write_text(text, encoding="utf-8")

    def run_script(self, name: str, *args: str, env: dict | None = None, cwd: Path | None = None):
        full_env = {**os.environ, **(env or {})}
        return subprocess.run(
            [str(SCRIPTS / name), *args], capture_output=True, text=True, check=False, env=full_env, cwd=cwd
        )

    def v(self, name: str, *args: str):
        return self.run_script(name, "--vault", str(self.vault), *args)


class CheckSources(VaultCase):
    def test_queue_matches_reference_rules(self) -> None:
        data = json.loads(self.v("check-sources.py", "--json").stdout)
        self.assertEqual([i["source"] for i in data["new"]], [BETA])
        self.assertEqual(data["new"][0]["sha256"], sha256(self.vault / BETA))
        self.assertEqual([i["source"] for i in data["changed"]], ["Twitter-Captures/tools/gamma.md"])
        self.assertEqual(data["unchanged_count"], 1)
        self.assertEqual(data["inbox_notes"], 1)

    def test_editing_a_raw_file_marks_it_changed(self) -> None:
        raw = self.vault / "Clippings/Alpha Article.md"
        raw.write_text(raw.read_text() + "More.\n", encoding="utf-8")
        data = json.loads(self.v("check-sources.py", "--json").stdout)
        self.assertIn("Clippings/Alpha Article.md", [i["source"] for i in data["changed"]])

    def test_exit_code_flag(self) -> None:
        self.assertEqual(self.v("check-sources.py", "--exit-code").returncode, 1)

    def test_vault_from_environment_and_cwd(self) -> None:
        by_env = self.run_script("check-sources.py", env={"CLAUDE_PROJECT_DIR": str(self.vault)}, cwd=SCRIPTS)
        by_cwd = self.run_script("check-sources.py", env={"CLAUDE_PROJECT_DIR": ""}, cwd=self.vault)
        self.assertIn("new sources: 1", by_env.stdout)
        self.assertIn("new sources: 1", by_cwd.stdout)


class Pages(VaultCase):
    def test_find_uses_names_and_aliases(self) -> None:
        out = json.loads(self.v("wiki-pages.py", "find", "--json", "acme corp", "ACME", "Nobody").stdout)
        self.assertEqual([r["status"] for r in out], ["exists", "exists", "new"])

    def test_bump_adds_the_mention_once(self) -> None:
        args = ("bump", "Compounding", "--source", "gamma", "--mention", "again")
        self.assertIn("1 -> 2", self.v("wiki-pages.py", *args).stdout)
        self.assertIn("skipped", self.v("wiki-pages.py", *args).stdout)
        text = (self.vault / "Wiki/concepts/compounding.md").read_text()
        self.assertIn("source_count: 2", text)
        self.assertEqual(text.count("[[gamma]]"), 1)

    def test_new_refuses_an_existing_page(self) -> None:
        r = self.v("wiki-pages.py", "new", "entity", "Acme Corp", "--kind", "org", "--source", "gamma")
        self.assertEqual(r.returncode, 2)


class Index(VaultCase):
    def test_rebuild_is_idempotent(self) -> None:
        self.assertEqual(self.v("rebuild-index.py", "--check").returncode, 1)
        self.v("rebuild-index.py")
        self.assertEqual(self.v("rebuild-index.py", "--check").returncode, 0)
        text = (self.vault / "Wiki/index.md").read_text()
        self.assertIn("[[alpha-article\\|Alpha Article]]", text)
        self.assertIn(BETA, text)

    def test_backfill_fills_a_missing_hash(self) -> None:
        page = self.vault / "Wiki/sources/alpha-article.md"
        page.write_text(re.sub(r"(?m)^source_hash:.*\n", "", page.read_text()), encoding="utf-8")
        self.v("backfill-hashes.py")
        self.assertIn(sha256(self.vault / "Clippings/Alpha Article.md"), page.read_text())


class Overview(VaultCase):
    def test_reworded_count_line_is_reported(self) -> None:
        path = self.vault / "Wiki/overview.md"
        path.write_text(path.read_text().replace("sources ingested", "sources done"), encoding="utf-8")
        result = self.v("update-overview.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no line in overview.md matches", result.stderr)


class Qmd(VaultCase):
    def test_skips_cleanly_without_qmd(self) -> None:
        r = self.run_script("qmd-refresh.py", env={"PATH": str(Path(shutil.which("uv")).parent)})
        self.assertEqual(r.returncode, 0)
        self.assertIn("not installed", r.stdout)


class FullIngest(VaultCase):
    def finish_pages(self) -> None:
        page = self.vault / "Wiki/sources/beta-the-sequel.md"
        text = page.read_text()
        text = re.sub(r"(?m)^TODO\(ingest\).*$", "Beta is about Acme.", text)
        text = re.sub(r"(?m)^- TODO\(ingest\) One claim.*$", "- Beta makes one claim.", text)
        text = re.sub(
            r"(?m)^- TODO\(ingest\) \[\[entity-slug\|Entity name\]\].*$", "- [[acme|Acme]] - the subject", text
        )
        text = re.sub(
            r"(?m)^- TODO\(ingest\) \[\[concept-slug\|Concept name\]\].*$",
            "- [[compounding|Compounding]] - the theme",
            text,
        )
        page.write_text(text, encoding="utf-8")

    def test_scaffold_finalize_commit(self) -> None:
        scaffold = self.v("scaffold-source.py", BETA)
        self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
        page = self.vault / "Wiki/sources/beta-the-sequel.md"
        text = page.read_text()
        self.assertIn(f'source_hash: "{sha256(self.vault / BETA)}"', text)
        self.assertIn('author: "Bo Writer"', text)

        blocked = self.v("finalize-ingest.py", "beta-the-sequel")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertNotIn("beta-the-sequel", (self.vault / "Wiki/log.md").read_text())

        self.finish_pages()
        self.assertEqual(
            self.v("wiki-pages.py", "bump", "Acme", "--source", "beta-the-sequel", "--mention", "subject").returncode, 0
        )
        self.assertEqual(
            self.v(
                "wiki-pages.py", "bump", "Compounding", "--source", "beta-the-sequel", "--mention", "theme"
            ).returncode,
            0,
        )
        done = self.v("finalize-ingest.py", "--note", "A test note.", "beta-the-sequel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        log = (self.vault / "Wiki/log.md").read_text()
        self.assertIn("ingest | Beta: The Sequel", log)
        self.assertIn("- Updated entities: [[acme|Acme]]", log)
        self.assertIn("- Note: A test note.", log)
        overview = (self.vault / "Wiki/overview.md").read_text()
        self.assertIn("synthesizes 3 sources", overview)
        self.assertIn("**3 of 3** sources ingested", overview)

        again = self.v("finalize-ingest.py", "beta-the-sequel")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(log, (self.vault / "Wiki/log.md").read_text())

        git = ["git", "-C", str(self.vault), "-c", "user.name=t", "-c", "user.email=t@example.test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        (self.vault / "Wiki/log.md").write_text(log + "\n", encoding="utf-8")
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.test",
        }
        committed = self.run_script("commit-ingest.py", "--vault", str(self.vault), "beta-the-sequel", env=env)
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        message = subprocess.run([*git, "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
        self.assertTrue(
            message.startswith("wiki: ingest beta-the-sequel\n\nSource: Clippings/Beta Article.md\nSHA-256: ")
        )


class NewPages(VaultCase):
    def test_new_writes_a_slug_file_with_title_and_aliases(self) -> None:
        r = self.v(
            "wiki-pages.py", "new", "concept", "MCP (Model Context Protocol)", "--confidence", "low",
            "--source", "gamma", "--alias", "MCP",
        )  # fmt: skip
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("link=[[mcp-model-context-protocol|MCP (Model Context Protocol)]]", r.stdout)
        text = (self.vault / "Wiki/concepts/mcp-model-context-protocol.md").read_text()
        self.assertIn('title: "MCP (Model Context Protocol)"', text)
        self.assertIn('aliases:\n  - "MCP (Model Context Protocol)"\n  - "MCP"\n', text)
        self.assertIn("# MCP (Model Context Protocol)", text)
        found = json.loads(self.v("wiki-pages.py", "find", "--json", "mcp model context protocol").stdout)
        self.assertEqual(found[0]["link"], "[[mcp-model-context-protocol|MCP (Model Context Protocol)]]")

    def test_new_refuses_a_slug_that_another_page_uses(self) -> None:
        r = self.v("wiki-pages.py", "new", "entity", "Alpha Article", "--kind", "tool", "--source", "gamma")
        self.assertEqual(r.returncode, 2)
        self.assertIn("already uses the file name alpha-article.md", r.stderr)
        ok = self.v(
            "wiki-pages.py", "new", "entity", "Alpha Article", "--kind", "tool", "--source", "gamma",
            "--slug", "alpha-article-tool",
        )  # fmt: skip
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue((self.vault / "Wiki/entities/alpha-article-tool.md").is_file())

    def test_new_refuses_a_title_with_no_ascii(self) -> None:
        r = self.v("wiki-pages.py", "new", "entity", "日本語", "--kind", "tool", "--source", "gamma")
        self.assertEqual(r.returncode, 2)


class Validator(VaultCase):
    def test_catches_hash_mismatch_and_broken_link(self) -> None:
        self.v("rebuild-index.py")
        self.v("update-overview.py")
        raw = self.vault / "Clippings/Alpha Article.md"
        raw.write_text(raw.read_text() + "Edit.\n", encoding="utf-8")
        page = self.vault / "Wiki/entities/acme.md"
        page.write_text(page.read_text() + "\nSee [[Nowhere]].\n", encoding="utf-8")
        r = self.v("validate-wiki.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("source_hash does not match", r.stdout)
        self.assertIn("broken link [[Nowhere]]", r.stdout)

    def test_ignores_links_in_code(self) -> None:
        page = self.vault / "Wiki/entities/acme.md"
        page.write_text(page.read_text() + "\n`[[Nowhere]]`\n", encoding="utf-8")
        self.assertNotIn("Nowhere", self.v("validate-wiki.py").stdout)

    def test_fails_on_a_space_in_a_page_file_name(self) -> None:
        (self.vault / "Wiki/concepts/compounding.md").rename(self.vault / "Wiki/concepts/Compounding Gains.md")
        r = self.v("validate-wiki.py", "--pages-only")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Wiki/concepts/Compounding Gains.md: file name has a space; use `compounding-gains.md`", r.stdout)

    def test_resolves_a_link_by_slug_and_by_alias(self) -> None:
        page = self.vault / "Wiki/entities/acme.md"
        page.write_text(page.read_text() + "\nSlug [[acme|Acme]]. Alias [[Acme Corp]].\n", encoding="utf-8")
        out = self.v("validate-wiki.py", "--pages-only").stdout
        self.assertNotIn("broken link", out)
        self.assertIn("link [[Acme Corp]] matches an alias, not a file name", out)
        self.assertNotIn("[[acme]]", out)


MIGRATE_PAGES = {
    "Wiki/concepts/Understanding LLM Output.md": """---
type: concept
confidence: low
date_created: 2026-01-01
date_updated: 2026-01-01
source_count: 1
tags:
  - wiki/concept
---

# Understanding LLM Output

See [[MCP (Model Context Protocol)#History]] and ![[Understanding LLM Output]].

```dataview
LIST FROM [[Understanding LLM Output]]
```
""",
    "Wiki/entities/MCP (Model Context Protocol).md": """---
type: entity
title: "MCP (Model Context Protocol)"
entity_kind: standard
aliases: [MCP]
date_created: 2026-01-01
date_updated: 2026-01-01
source_count: 1
tags:
  - wiki/entity
---

# MCP (Model Context Protocol)

Back to [[Understanding LLM Output|the output page]] and [[Understanding LLM Output#Part^abc]].
""",
    "Ideas/an-idea.md": "Idea about [[Understanding LLM Output]] and [[Wiki/entities/MCP (Model Context Protocol)]].\n",
    "Inbox/Tasks.md": "| Page | Note |\n|---|---|\n| [[Understanding LLM Output]] | x |\n",
    "Clippings/Link Holder.md": "Raw note about [[Understanding LLM Output]].\n",
}


class Migrate(VaultCase):
    def setUp(self) -> None:
        super().setUp()
        for rel, text in MIGRATE_PAGES.items():
            path = self.vault / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.raw = (self.vault / "Clippings/Link Holder.md").read_bytes()

    def tree(self) -> dict[str, bytes]:
        return {p.relative_to(self.vault).as_posix(): p.read_bytes() for p in self.vault.rglob("*") if p.is_file()}

    def test_dry_run_prints_the_plan_and_writes_nothing(self) -> None:
        before = self.tree()
        r = self.v("migrate-slugs.py", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Rename map (2 page(s))", r.stdout)
        self.assertIn(
            "Wiki/concepts/Understanding LLM Output.md -> Wiki/concepts/understanding-llm-output.md", r.stdout
        )
        self.assertIn("Wiki/entities/mcp-model-context-protocol.md", r.stdout)
        self.assertIn("Inbox/Tasks.md: 1", r.stdout)
        self.assertIn("Ideas/an-idea.md: 2", r.stdout)
        self.assertIn("Clippings/Link Holder.md: 1", r.stdout)
        self.assertEqual(before, self.tree())

    def test_migrates_names_links_and_frontmatter(self) -> None:
        r = self.v("migrate-slugs.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = [p.name for p in (self.vault / "Wiki").rglob("*.md")]
        self.assertFalse([n for n in names if " " in n])

        concept = (self.vault / "Wiki/concepts/understanding-llm-output.md").read_text()
        self.assertIn('title: "Understanding LLM Output"', concept)
        self.assertIn('aliases:\n  - "Understanding LLM Output"\n', concept)
        self.assertIn(
            "[[mcp-model-context-protocol#History|MCP (Model Context Protocol)]] and ![[understanding-llm-output]].",
            concept,
        )
        self.assertIn("LIST FROM [[Understanding LLM Output]]", concept)

        entity = (self.vault / "Wiki/entities/mcp-model-context-protocol.md").read_text()
        self.assertIn('aliases:\n  - "MCP"\n  - "MCP (Model Context Protocol)"\n', entity)
        self.assertIn("[[understanding-llm-output|the output page]]", entity)
        self.assertIn("[[understanding-llm-output#Part^abc|Understanding LLM Output]]", entity)

        idea = (self.vault / "Ideas/an-idea.md").read_text()
        self.assertIn("[[understanding-llm-output|Understanding LLM Output]]", idea)
        self.assertIn("[[Wiki/entities/mcp-model-context-protocol|MCP (Model Context Protocol)]]", idea)
        self.assertIn(
            "| [[understanding-llm-output\\|Understanding LLM Output]] | x |",
            (self.vault / "Inbox/Tasks.md").read_text(),
        )

        self.assertEqual(self.raw, (self.vault / "Clippings/Link Holder.md").read_bytes())
        log = (self.vault / "Wiki/log.md").read_text()
        self.assertIn("migrate | Slug file names", log)
        self.assertIn("- Renamed: 2 pages", log)
        index = (self.vault / "Wiki/index.md").read_text()
        self.assertIn("[[understanding-llm-output\\|Understanding LLM Output]]", index)
        self.assertEqual(self.v("rebuild-index.py", "--check").returncode, 0)
        out = self.v("validate-wiki.py", "--pages-only")
        self.assertNotIn("broken link", out.stdout)
        self.assertNotIn("file name has a space", out.stdout)

    def test_second_run_does_nothing(self) -> None:
        self.v("migrate-slugs.py")
        before = self.tree()
        r = self.v("migrate-slugs.py")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to do", r.stdout)
        self.assertEqual(before, self.tree())

    def test_uses_git_mv_in_a_repository(self) -> None:
        git = ["git", "-C", str(self.vault), "-c", "user.name=t", "-c", "user.email=t@example.test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        self.assertEqual(self.v("migrate-slugs.py").returncode, 0)
        status = subprocess.run([*git, "status", "--short"], capture_output=True, text=True).stdout
        self.assertRegex(status, r"(?m)^R.? +.*Understanding LLM Output\.md\"? -> .*understanding-llm-output\.md")

    def test_refuses_on_a_collision_and_writes_nothing(self) -> None:
        clash = self.vault / "Wiki/concepts/Understanding-LLM Output.md"
        clash.write_text(MIGRATE_PAGES["Wiki/concepts/Understanding LLM Output.md"], encoding="utf-8")
        before = self.tree()
        r = self.v("migrate-slugs.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("1 collision(s)", r.stdout)
        self.assertIn("understanding-llm-output", r.stdout)
        self.assertIn("Wiki/concepts/Understanding-LLM Output.md", r.stdout)
        self.assertEqual(before, self.tree())

    def test_refuses_when_a_slug_matches_an_existing_note(self) -> None:
        (self.vault / "Wiki/sources/understanding-llm-output.md").write_text("x\n", encoding="utf-8")
        r = self.v("migrate-slugs.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Wiki/sources/understanding-llm-output.md", r.stdout)

    def test_slug_option_settles_a_collision(self) -> None:
        (self.vault / "Wiki/sources/understanding-llm-output.md").write_text("x\n", encoding="utf-8")
        r = self.v("migrate-slugs.py", "--slug", "Understanding LLM Output=llm-output-concept")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.vault / "Wiki/concepts/llm-output-concept.md").is_file())
        idea = (self.vault / "Ideas/an-idea.md").read_text()
        self.assertIn("[[llm-output-concept|Understanding LLM Output]]", idea)


if __name__ == "__main__":
    unittest.main()
