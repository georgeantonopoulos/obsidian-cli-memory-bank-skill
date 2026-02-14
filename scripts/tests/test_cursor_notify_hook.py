#!/usr/bin/env python3
import unittest

from scripts.cursor_notify_hook import extract_prompt, extract_summary


class CursorNotifyHookTests(unittest.TestCase):
    def test_extract_prompt_from_conversation(self) -> None:
        payload = {
            "conversation": [
                {"author": "user", "text": "Add MKV audio copy fallback logs."},
                {"author": "assistant", "text": "Sure, adding that now."},
            ]
        }
        out = extract_prompt(payload)
        self.assertIn("MKV audio copy", out)

    def test_extract_summary_from_assistant_message(self) -> None:
        payload = {"assistant_message": "Added fallback logs and updated tests."}
        out = extract_summary(payload)
        self.assertEqual(out, "Added fallback logs and updated tests.")


if __name__ == "__main__":
    unittest.main()
