"""Unit tests for the slug function and the wikilink rewrite.

Run with: python3 -m unittest discover -s skills/wiki-ingest/tests
These tests import the helpers directly and need no PyYAML.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import _wikilib as wl  # noqa: E402
import _wikimigrate as mig  # noqa: E402

VAULT = Path("/vault")


def lookup(*pairs: tuple[str, str]) -> dict[str, mig.Rename]:
    renames = [
        mig.Rename(
            VAULT / "Wiki/concepts" / f"{old}.md", VAULT / "Wiki/concepts" / f"{wl.page_slug(title)}.md", title, old
        )
        for old, title in pairs
    ]
    return mig.lookup_for(renames)


class PageSlug(unittest.TestCase):
    def test_examples_from_the_convention(self) -> None:
        self.assertEqual(wl.page_slug("MCP (Model Context Protocol)"), "mcp-model-context-protocol")
        self.assertEqual(wl.page_slug("Exploration-Exploitation Trade-off"), "exploration-exploitation-trade-off")
        self.assertEqual(wl.page_slug("Understanding LLM Output"), "understanding-llm-output")

    def test_separators_collapse_and_trim(self) -> None:
        self.assertEqual(wl.page_slug("  --A  /  b__c--  "), "a-b-c")
        self.assertEqual(wl.page_slug("C++ & C#"), "c-c")

    def test_accents_fold_to_ascii(self) -> None:
        self.assertEqual(wl.page_slug("Café Münch"), "cafe-munch")
        self.assertEqual(wl.page_slug("Naïve Bayes"), "naive-bayes")

    def test_output_is_ascii_lowercase_without_spaces(self) -> None:
        slug = wl.page_slug("Ünïcode: Ça Va? 100% — “quoted”")
        self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_page_slug_never_truncates(self) -> None:
        title = "word " * 30
        self.assertEqual(wl.page_slug(title), "-".join(["word"] * 30))

    def test_no_ascii_gives_an_empty_slug(self) -> None:
        self.assertEqual(wl.page_slug("日本語"), "")

    def test_source_slugs_still_truncate_and_fall_back(self) -> None:
        self.assertLessEqual(len(wl.slugify("word " * 30)), wl.SLUG_LIMIT)
        self.assertEqual(wl.slugify("日本語"), "untitled")


class Apostrophes(unittest.TestCase):
    def test_straight_and_curly_apostrophes_are_deleted(self) -> None:
        self.assertEqual(wl.page_slug("AI's Best Engineering Teams"), "ais-best-engineering-teams")
        self.assertEqual(wl.page_slug("AI\u2019s Best Engineering Teams"), "ais-best-engineering-teams")
        self.assertEqual(wl.page_slug("Don't 'quote' me"), "dont-quote-me")

    def test_other_punctuation_still_breaks_a_word(self) -> None:
        self.assertEqual(wl.page_slug("a-b/c's"), "a-b-cs")


class ClipSlug(unittest.TestCase):
    def test_a_short_name_is_the_page_slug(self) -> None:
        self.assertEqual(wl.clip_slug("Post by @karpathy on X"), "post-by-karpathy-on-x")

    def test_a_long_title_is_capped_at_80(self) -> None:
        slug = wl.clip_slug("word " * 40)
        self.assertLessEqual(len(slug), wl.CLIP_SLUG_LIMIT)
        self.assertEqual(slug, "-".join(["word"] * 16))  # 16 words = 79 characters

    def test_the_cut_is_at_the_last_hyphen_at_or_before_80(self) -> None:
        # 79 + hyphen at index 79, then a word: the cut keeps 79 characters.
        title = "a" * 79 + " tail"
        self.assertEqual(wl.clip_slug(title), "a" * 79)
        # A hyphen at index 80 keeps exactly 80 characters.
        title = "a" * 80 + " tail"
        self.assertEqual(wl.clip_slug(title), "a" * 80)
        # A word that crosses 80 is dropped whole.
        title = "a" * 70 + " " + "b" * 20
        self.assertEqual(wl.clip_slug(title), "a" * 70)

    def test_no_trailing_hyphen(self) -> None:
        for title in ("a" * 80 + " b", "a " * 60, "x" * 79 + "- - -y" * 5, "a" * 100):
            slug = wl.clip_slug(title)
            self.assertFalse(slug.endswith("-"), slug)
            self.assertLessEqual(len(slug), 80)

    def test_a_name_with_no_hyphen_is_cut_at_80(self) -> None:
        self.assertEqual(wl.clip_slug("a" * 100), "a" * 80)

    def test_the_result_is_stable(self) -> None:
        slug = wl.clip_slug("word " * 40)
        self.assertEqual(wl.clip_slug(slug), slug)
        self.assertFalse(wl.needs_slug(slug))
        self.assertTrue(wl.needs_slug("a" * 100))

    def test_wiki_page_slugs_stay_uncapped(self) -> None:
        self.assertEqual(len(wl.page_slug("word " * 40)), 199)


class WikiLink(unittest.TestCase):
    def test_link_forms(self) -> None:
        self.assertEqual(wl.wikilink("a-b", "A B"), "[[a-b|A B]]")
        self.assertEqual(wl.wikilink("a-b", "A B", table=True), "[[a-b\\|A B]]")
        self.assertEqual(wl.wikilink("a", "a"), "[[a]]")

    def test_target_ignores_alias_heading_and_table_escape(self) -> None:
        self.assertEqual(wl.wikilink_target("a-b\\|A B"), "a-b")
        self.assertEqual(wl.wikilink_target("a-b#Head|A B"), "a-b")


class RewriteLinks(unittest.TestCase):
    table = lookup(("Old Name", "Old Name"), ("MCP (Model Context Protocol)", "MCP (Model Context Protocol)"))

    def rewrite(self, text: str) -> tuple[str, int]:
        return mig.rewrite_links(text, self.table, VAULT)

    def test_plain_link_gets_the_title(self) -> None:
        self.assertEqual(self.rewrite("See [[Old Name]]."), ("See [[old-name|Old Name]].", 1))

    def test_display_text_is_kept(self) -> None:
        self.assertEqual(self.rewrite("[[Old Name|the page]]"), ("[[old-name|the page]]", 1))

    def test_heading_is_kept(self) -> None:
        self.assertEqual(self.rewrite("[[Old Name#Part]]"), ("[[old-name#Part|Old Name]]", 1))
        self.assertEqual(self.rewrite("[[Old Name#Part|text]]"), ("[[old-name#Part|text]]", 1))

    def test_block_reference_is_kept(self) -> None:
        self.assertEqual(self.rewrite("[[Old Name#^abc123]]"), ("[[old-name#^abc123|Old Name]]", 1))

    def test_embed_keeps_its_form(self) -> None:
        self.assertEqual(self.rewrite("![[Old Name]]"), ("![[old-name]]", 1))
        self.assertEqual(self.rewrite("![[Old Name#Part]]"), ("![[old-name#Part]]", 1))

    def test_table_row_escapes_the_pipe(self) -> None:
        self.assertEqual(self.rewrite("| [[Old Name]] | x |"), ("| [[old-name\\|Old Name]] | x |", 1))
        self.assertEqual(self.rewrite("| [[Old Name\\|text]] |"), ("| [[old-name\\|text]] |", 1))

    def test_title_with_punctuation(self) -> None:
        text, n = self.rewrite("[[MCP (Model Context Protocol)]]")
        self.assertEqual((text, n), ("[[mcp-model-context-protocol|MCP (Model Context Protocol)]]", 1))

    def test_path_prefix_and_extension_are_kept(self) -> None:
        self.assertEqual(self.rewrite("[[Wiki/concepts/Old Name]]"), ("[[Wiki/concepts/old-name|Old Name]]", 1))
        self.assertEqual(self.rewrite("[[Old Name.md]]"), ("[[old-name.md|Old Name]]", 1))
        self.assertEqual(self.rewrite("[[Other/Old Name]]"), ("[[Other/Old Name]]", 0))

    def test_match_ignores_case(self) -> None:
        self.assertEqual(self.rewrite("[[old name]]"), ("[[old-name|Old Name]]", 1))

    def test_code_and_unrelated_links_stay(self) -> None:
        text = "`[[Old Name]]`\n```dataview\nFROM [[Old Name]]\n```\n[[Elsewhere]]\n"
        self.assertEqual(self.rewrite(text), (text, 0))

    def test_counts_every_link(self) -> None:
        self.assertEqual(self.rewrite("[[Old Name]] and ![[Old Name]] and [[Old Name#H|x]]")[1], 3)


class FrontmatterEdit(unittest.TestCase):
    """These need PyYAML, so they skip when it is missing."""

    def setUp(self) -> None:
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyYAML is not installed")

    def test_adds_title_and_a_block_of_aliases_before_tags(self) -> None:
        text = "---\ntype: concept\ntags:\n  - x\n---\n\nBody\n"
        out = mig.add_title_and_aliases(text, "Old Name", "Old Name")
        self.assertEqual(
            out, '---\ntype: concept\ntitle: "Old Name"\naliases:\n  - "Old Name"\ntags:\n  - x\n---\n\nBody\n'
        )

    def test_keeps_existing_aliases_and_adds_the_old_name(self) -> None:
        text = '---\ntitle: "T"\naliases:\n  - "A"\ntags: []\n---\nBody\n'
        out = mig.add_title_and_aliases(text, "T", "Old T")
        self.assertIn('aliases:\n  - "A"\n  - "T"\n  - "Old T"\ntags', out)

    def test_leaves_a_page_that_is_complete(self) -> None:
        text = '---\ntitle: "T"\naliases:\n  - "T"\n---\nBody\n'
        self.assertEqual(mig.add_title_and_aliases(text, "T", "T"), text)

    def test_page_without_frontmatter_gets_one(self) -> None:
        out = mig.add_title_and_aliases("Body\n", "T", "T")
        self.assertTrue(out.startswith('---\ntitle: "T"\naliases:\n  - "T"\n---\n'))


if __name__ == "__main__":
    unittest.main()
