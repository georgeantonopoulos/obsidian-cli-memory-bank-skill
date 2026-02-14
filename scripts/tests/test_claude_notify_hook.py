#!/usr/bin/env python3
import unittest

from scripts.claude_notify_hook import extract_prompt, extract_summary


class ClaudeNotifyHookTests(unittest.TestCase):
    def test_extract_prompt_from_messages(self) -> None:
        payload = {
            "messages": [
                {"role": "user", "content": "Please fix export queue retries."},
                {"role": "assistant", "content": "I can help with that."},
            ]
        }
        out = extract_prompt(payload)
        self.assertIn("fix export queue retries", out)

    def test_extract_summary_prefers_assistant_field(self) -> None:
        payload = {"assistant": "Implemented queue retry handling and tests."}
        out = extract_summary(payload)
        self.assertIn("Implemented queue retry", out)


if __name__ == "__main__":
    unittest.main()
