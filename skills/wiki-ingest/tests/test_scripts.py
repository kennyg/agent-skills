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
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import _wikiclips as clips  # noqa: E402

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
        digest = sha256(self.vault / BETA)
        scaffold = self.v("scaffold-source.py", BETA)
        self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
        page = self.vault / "Wiki/sources/beta-the-sequel.md"
        text = page.read_text()
        self.assertIn(f'source_hash: "{digest}"', text)
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
            message.startswith("wiki: ingest beta-the-sequel\n\nSource: Clippings/beta-article.md\nSHA-256: ")
        )

    def test_commit_holds_the_clipping_rename(self) -> None:
        git = ["git", "-C", str(self.vault), "-c", "user.name=t", "-c", "user.email=t@example.test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        raw = (self.vault / BETA).read_bytes()
        self.assertEqual(self.v("scaffold-source.py", BETA).returncode, 0)
        staged = subprocess.run([*git, "status", "--short"], capture_output=True, text=True).stdout
        self.assertRegex(staged, r"(?m)^R +\"?Clippings/Beta Article\.md\"? -> Clippings/beta-article\.md")
        self.finish_pages()
        for name, mention in (("Acme", "subject"), ("Compounding", "theme")):
            self.v("wiki-pages.py", "bump", name, "--source", "beta-the-sequel", "--mention", mention)
        self.assertEqual(self.v("finalize-ingest.py", "beta-the-sequel").returncode, 0)
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.test",
        }
        done = self.run_script("commit-ingest.py", "--vault", str(self.vault), "beta-the-sequel", env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        shown = subprocess.run(
            [*git, "show", "--name-status", "-M", "--format=", "HEAD"], capture_output=True, text=True
        )
        self.assertRegex(shown.stdout, r"(?m)^R100\t\"?Clippings/Beta Article\.md\"?\tClippings/beta-article\.md")
        self.assertEqual(raw, (self.vault / "Clippings/beta-article.md").read_bytes())
        left = subprocess.run([*git, "status", "--short", "--", "Clippings"], capture_output=True, text=True).stdout
        self.assertEqual(left, "")


class ClippingRename(VaultCase):
    def test_ingest_renames_the_clipping_and_keeps_its_bytes(self) -> None:
        before = (self.vault / BETA).read_bytes()
        r = self.v("scaffold-source.py", BETA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("renamed Clippings/Beta Article.md -> Clippings/beta-article.md", r.stdout)
        self.assertFalse((self.vault / BETA).exists())
        renamed = self.vault / "Clippings/beta-article.md"
        self.assertEqual(before, renamed.read_bytes())
        page = (self.vault / "Wiki/sources/beta-the-sequel.md").read_text()
        self.assertIn('source_path: "Clippings/beta-article.md"', page)
        self.assertIn("[[Clippings/beta-article|Original note]]", page)

    def test_source_hash_is_the_hash_before_the_rename(self) -> None:
        digest = sha256(self.vault / BETA)
        self.v("scaffold-source.py", BETA)
        page = (self.vault / "Wiki/sources/beta-the-sequel.md").read_text()
        self.assertIn(f'source_hash: "{digest}"', page)
        self.assertEqual(sha256(self.vault / "Clippings/beta-article.md"), digest)
        out = json.loads(self.v("check-sources.py", "--json").stdout)
        self.assertEqual(out["new"], [])
        self.assertEqual(out["renamed"], [])

    def test_a_name_that_is_already_a_slug_stays(self) -> None:
        keep = self.vault / "Clippings/already-a-slug.md"
        keep.write_text('---\ntitle: "Already a slug"\n---\nBody\n', encoding="utf-8")
        r = self.v("scaffold-source.py", "Clippings/already-a-slug.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("renamed", r.stdout)
        self.assertTrue(keep.is_file())

    def test_a_capture_is_never_renamed(self) -> None:
        capture = self.vault / "Twitter-Captures/tools/Spaced Capture.md"
        capture.write_text('---\ntitle: "Spaced"\n---\nBody\n', encoding="utf-8")
        r = self.v("scaffold-source.py", "Twitter-Captures/tools/Spaced Capture.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(capture.is_file())

    def test_refuses_when_the_new_name_is_taken(self) -> None:
        taken = self.vault / "Clippings/beta-article.md"
        taken.write_text("Another clipping.\n", encoding="utf-8")
        r = self.v("scaffold-source.py", BETA)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot rename Clippings/Beta Article.md to beta-article.md", r.stderr)
        self.assertIn("Clippings/beta-article.md", r.stderr)
        self.assertIn("--clip-slug", r.stderr)
        self.assertTrue((self.vault / BETA).is_file())
        self.assertFalse((self.vault / "Wiki/sources/beta-the-sequel.md").exists())

    def test_clip_slug_chooses_the_name(self) -> None:
        (self.vault / "Clippings/beta-article.md").write_text("Another clipping.\n", encoding="utf-8")
        r = self.v("scaffold-source.py", BETA, "--clip-slug", "beta-the-sequel-clip")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.vault / "Clippings/beta-the-sequel-clip.md").is_file())
        page = (self.vault / "Wiki/sources/beta-the-sequel.md").read_text()
        self.assertIn('source_path: "Clippings/beta-the-sequel-clip.md"', page)

    def test_clip_slug_must_be_a_slug(self) -> None:
        r = self.v("scaffold-source.py", BETA, "--clip-slug", "Not A Slug")
        self.assertEqual(r.returncode, 2)
        self.assertTrue((self.vault / BETA).is_file())

    def test_warns_when_a_wiki_page_has_the_same_name(self) -> None:
        (self.vault / "Wiki/concepts/beta-article.md").write_text("x\n", encoding="utf-8")
        r = self.v("scaffold-source.py", BETA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("beta-article.md has the same note name as Wiki/concepts/beta-article.md", r.stderr)

    def test_warns_when_the_new_source_page_has_the_same_name(self) -> None:
        r = self.v("scaffold-source.py", BETA, "--slug", "beta-article")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("same note name as the new page Wiki/sources/beta-article.md", r.stderr)

    def test_a_hand_renamed_clipping_is_renamed_not_new(self) -> None:
        (self.vault / "Clippings/Alpha Article.md").rename(self.vault / "Clippings/alpha.md")
        data = json.loads(self.v("check-sources.py", "--json").stdout)
        self.assertEqual([i["source"] for i in data["new"]], [BETA])
        self.assertEqual(
            [(i["source"], i["was"]) for i in data["renamed"]],
            [("Clippings/alpha.md", "Clippings/Alpha Article.md")],
        )
        text = self.v("check-sources.py").stdout
        self.assertIn("renamed:  Clippings/alpha.md  <-  Clippings/Alpha Article.md", text)
        self.assertNotIn("new:      Clippings/alpha.md", text)
        queue = self.v("rebuild-index.py")
        self.assertNotIn("alpha.md | new", (self.vault / "Wiki/index.md").read_text(), queue.stdout)
        found = self.v("validate-wiki.py", "--pages-only").stdout
        self.assertIn("the same content is at Clippings/alpha.md, so set `source_path` to it", found)

    def test_validate_warns_about_a_clipping_that_is_not_a_slug(self) -> None:
        out = self.v("validate-wiki.py", "--pages-only").stdout
        self.assertIn("2 clipping(s) have a file name that is not a slug; run slug-clippings.py", out)
        self.v("scaffold-source.py", BETA)
        scoped = self.v("validate-wiki.py", "--pages-only", "--source", "beta-the-sequel").stdout
        self.assertNotIn("not a slug", scoped)


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


BACKFILL_FILES = {
    "Ideas/an-idea.md": "See [[Clippings/Beta Article|the sequel]] and [[Alpha Article]].\n",
    "Inbox/Tasks.md": "| Clip | Note |\n|---|---|\n| [[Clippings/Alpha Article]] | x |\n",
    "Clippings/Beta Article.md": None,  # keep the fixture content
    "Clippings/Link Holder.md": "A raw note that links [[Clippings/Beta Article]].\n",
}


class Backfill(VaultCase):
    def setUp(self) -> None:
        super().setUp()
        for rel, text in BACKFILL_FILES.items():
            if text is not None:
                path = self.vault / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        self.raw = {p: (self.vault / p).read_bytes() for p in ("Clippings/Alpha Article.md", BETA)}

    def tree(self) -> dict[str, bytes]:
        return {p.relative_to(self.vault).as_posix(): p.read_bytes() for p in self.vault.rglob("*") if p.is_file()}

    def test_dry_run_prints_the_plan_and_writes_nothing(self) -> None:
        before = self.tree()
        r = self.v("slug-clippings.py", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Rename map (3 clipping(s))", r.stdout)
        self.assertIn("Clippings/Alpha Article.md -> Clippings/alpha-article.md", r.stdout)
        self.assertIn("Clippings/Link Holder.md -> Clippings/link-holder.md", r.stdout)
        self.assertIn("Source pages to change (1)", r.stdout)
        self.assertIn("Wiki/sources/alpha-article.md: source_path Clippings/Alpha Article.md", r.stdout)
        self.assertIn("Ideas/an-idea.md: 2", r.stdout)
        self.assertIn("Inbox/Tasks.md: 1", r.stdout)
        self.assertIn("Clippings/Link Holder.md: 1", r.stdout)  # a link the script does not edit
        self.assertIn("Name clashes with notes in other folders (1)", r.stdout)
        self.assertIn("Wiki/sources/alpha-article.md", r.stdout)
        self.assertIn("No collisions. Dry run: nothing written.", r.stdout)
        self.assertEqual(before, self.tree())

    def test_real_run_renames_and_rewrites(self) -> None:
        r = self.v("slug-clippings.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.vault / "Clippings/Alpha Article.md").exists())
        self.assertEqual(
            self.raw["Clippings/Alpha Article.md"], (self.vault / "Clippings/alpha-article.md").read_bytes()
        )
        self.assertEqual(self.raw[BETA], (self.vault / "Clippings/beta-article.md").read_bytes())
        self.assertEqual(
            "A raw note that links [[Clippings/Beta Article]].\n",
            (self.vault / "Clippings/link-holder.md").read_text(),
        )

        page = (self.vault / "Wiki/sources/alpha-article.md").read_text()
        self.assertIn('source_path: "Clippings/alpha-article.md"', page)
        self.assertIn("[[Clippings/alpha-article|Original note]]", page)
        self.assertIn(f'source_hash: "{sha256(self.vault / "Clippings/alpha-article.md")}"', page)

        idea = (self.vault / "Ideas/an-idea.md").read_text()
        self.assertIn("[[Clippings/beta-article|the sequel]]", idea)
        self.assertIn("[[alpha-article|Alpha Article]]", idea)
        self.assertIn(
            "| [[Clippings/alpha-article\\|Alpha Article]] | x |", (self.vault / "Inbox/Tasks.md").read_text()
        )

        log = (self.vault / "Wiki/log.md").read_text()
        self.assertIn("migrate | Slug clipping names", log)
        self.assertIn("- Renamed: 3 clippings", log)
        self.assertIn("Clippings/alpha-article.md", (self.vault / "Wiki/index.md").read_text())
        self.assertEqual(self.v("rebuild-index.py", "--check").returncode, 0)

        out = self.v("check-sources.py", "--json").stdout
        data = json.loads(out)
        self.assertEqual([i["source"] for i in data["new"]], ["Clippings/beta-article.md", "Clippings/link-holder.md"])
        self.assertEqual((data["changed"][0]["source"], data["renamed"]), ("Twitter-Captures/tools/gamma.md", []))
        self.assertEqual(data["unchanged_count"], 1)
        checked = self.v("validate-wiki.py", "--pages-only")
        self.assertNotIn("Clippings", checked.stdout)
        self.assertNotIn("alpha", checked.stdout)

    def test_uses_git_mv_in_a_repository(self) -> None:
        git = ["git", "-C", str(self.vault), "-c", "user.name=t", "-c", "user.email=t@example.test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        self.assertEqual(self.v("slug-clippings.py").returncode, 0)
        status = subprocess.run([*git, "status", "--short"], capture_output=True, text=True).stdout
        self.assertRegex(status, r"(?m)^R.? +\"?Clippings/Alpha Article\.md\"? -> Clippings/alpha-article\.md")

    def test_second_run_does_nothing(self) -> None:
        self.v("slug-clippings.py")
        before = self.tree()
        r = self.v("slug-clippings.py")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to do", r.stdout)
        self.assertEqual(before, self.tree())

    def test_refuses_on_a_collision_and_writes_nothing(self) -> None:
        (self.vault / "Clippings/alpha-article.md").write_text("Taken.\n", encoding="utf-8")
        (self.vault / "Clippings/Alpha-Article!.md").write_text("Same slug.\n", encoding="utf-8")
        before = self.tree()
        r = self.v("slug-clippings.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("collision(s)", r.stdout)
        self.assertIn("Clippings/alpha-article.md", r.stdout)
        self.assertIn("Clippings/Alpha-Article!.md", r.stdout)
        self.assertEqual(before, self.tree())

    def test_clip_slug_settles_a_collision(self) -> None:
        (self.vault / "Clippings/alpha-article.md").write_text("Taken.\n", encoding="utf-8")
        r = self.v("slug-clippings.py", "--clip-slug", "Alpha Article=alpha-clip")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.raw["Clippings/Alpha Article.md"], (self.vault / "Clippings/alpha-clip.md").read_bytes())
        page = (self.vault / "Wiki/sources/alpha-article.md").read_text()
        self.assertIn('source_path: "Clippings/alpha-clip.md"', page)

    def test_clip_slug_must_be_a_slug(self) -> None:
        self.assertEqual(self.v("slug-clippings.py", "--clip-slug", "Alpha Article=Not A Slug").returncode, 2)

    def test_a_name_over_the_file_name_limit_is_a_collision(self) -> None:
        old = self.vault / "Clippings/Alpha Article.md"
        new = self.vault / ("Clippings/" + "word-" * 60 + ".md")
        collisions, _ = clips.check_targets(self.vault, [(old, new)])
        self.assertEqual(len(collisions), 1)
        self.assertIn("name is longer than 255 bytes", next(iter(collisions)))


if __name__ == "__main__":
    unittest.main()
