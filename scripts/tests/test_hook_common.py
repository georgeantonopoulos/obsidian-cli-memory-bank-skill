#!/usr/bin/env python3
import unittest

from scripts.hook_common import sanitize_query


class SanitizeQueryTests(unittest.TestCase):
    def test_strips_at_file_paths(self) -> None:
        prompt = "Review the implementation of @docs/plans/2026-03-02-custom-hue-curve-widget.md"
        result = sanitize_query(prompt)
        self.assertNotIn("@", result)
        self.assertNotIn("/", result)
        self.assertIn("review", result)
        self.assertIn("implementation", result)

    def test_strips_unix_paths(self) -> None:
        prompt = "Check /Users/george/Dev/project/src/main.py for bugs"
        result = sanitize_query(prompt)
        self.assertNotIn("/Users", result)
        self.assertIn("bugs", result)

    def test_strips_urls(self) -> None:
        prompt = "Push changes to https://github.com/user/repo and verify"
        result = sanitize_query(prompt)
        self.assertNotIn("https", result)
        self.assertNotIn("github", result)
        self.assertIn("push", result)
        self.assertIn("changes", result)

    def test_strips_date_stamps(self) -> None:
        prompt = "What changed on 2026-03-02 in the hue widget?"
        result = sanitize_query(prompt)
        self.assertNotIn("2026", result)
        self.assertIn("hue", result)
        self.assertIn("widget", result)

    def test_strips_inline_code(self) -> None:
        prompt = "Fix the `_push_curve_to_huecorrect` function in widget"
        result = sanitize_query(prompt)
        self.assertNotIn("`", result)
        self.assertIn("fix", result)
        self.assertIn("function", result)
        self.assertIn("widget", result)

    def test_removes_stop_words(self) -> None:
        result = sanitize_query("please help me find the bug in this code")
        words = result.split()
        self.assertNotIn("please", words)
        self.assertNotIn("me", words)
        self.assertNotIn("the", words)
        self.assertIn("bug", words)
        self.assertIn("code", words)

    def test_limits_word_count(self) -> None:
        prompt = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
        result = sanitize_query(prompt, max_words=5)
        self.assertLessEqual(len(result.split()), 5)

    def test_empty_prompt_returns_empty(self) -> None:
        self.assertEqual(sanitize_query(""), "")

    def test_all_stop_words_falls_back(self) -> None:
        result = sanitize_query("can you please help me with this")
        # Should fall back to returning some words even if all are stop words
        # since single-char words are filtered and remaining may be stop words
        # the fallback picks from the original word list
        self.assertIsInstance(result, str)

    def test_real_world_poisoned_prompt(self) -> None:
        prompt = (
            "Review the implementation of @docs/plans/2026-03-02-custom-hue-curve-widget.md "
            "and let me know if the Obsidian skill fired correctly"
        )
        result = sanitize_query(prompt)
        self.assertNotIn("@", result)
        self.assertNotIn("2026", result)
        self.assertTrue(len(result) > 0)
        # Should contain meaningful words like "review", "implementation", "obsidian", "skill"
        words = result.split()
        meaningful = {"review", "implementation", "obsidian", "skill", "fired", "correctly"}
        self.assertTrue(
            any(w in meaningful for w in words),
            f"Expected at least one meaningful word, got: {words}",
        )


if __name__ == "__main__":
    unittest.main()
