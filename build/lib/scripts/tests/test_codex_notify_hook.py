#!/usr/bin/env python3
import unittest

from scripts.codex_notify_hook import extract_prompt, extract_summary, slug_to_title, truncate


class CodexNotifyHookTests(unittest.TestCase):
    def test_truncate(self) -> None:
        self.assertEqual(truncate("short", 10), "short")
        self.assertTrue(truncate("x" * 20, 10).endswith("..."))

    def test_slug_to_title(self) -> None:
        title = slug_to_title("Codex Turn 12345 fix exporter progress display now")
        self.assertEqual(title, "Codex Turn 12345 fix exporter progress display now")

    def test_extract_prompt_from_string_messages(self) -> None:
        payload = {"input-messages": ["First prompt", "Second prompt"]}
        out = extract_prompt(payload)
        self.assertIn("First prompt", out)
        self.assertIn("Second prompt", out)

    def test_extract_summary(self) -> None:
        payload = {"last-assistant-message": "Completed update and tests passed."}
        out = extract_summary(payload)
        self.assertEqual(out, "Completed update and tests passed.")


if __name__ == "__main__":
    unittest.main()
