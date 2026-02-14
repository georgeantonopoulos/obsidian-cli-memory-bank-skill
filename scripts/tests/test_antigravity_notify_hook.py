#!/usr/bin/env python3
import unittest

from scripts.antigravity_notify_hook import extract_prompt, extract_summary


class AntigravityNotifyHookTests(unittest.TestCase):
    def test_extract_prompt_from_messages(self) -> None:
        payload = {
            "messages": [
                {"role": "user", "content": "Track exporter perf by frame count."},
                {"role": "assistant", "content": "Done and validated."},
            ]
        }
        out = extract_prompt(payload)
        self.assertIn("Track exporter perf", out)

    def test_extract_summary_from_output(self) -> None:
        payload = {"output": "Wired frame-count progress and passed tests."}
        out = extract_summary(payload)
        self.assertIn("frame-count progress", out)


if __name__ == "__main__":
    unittest.main()
