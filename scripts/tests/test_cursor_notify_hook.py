#!/usr/bin/env python3
import hashlib
import hmac
import os
import unittest

from scripts.cursor_notify_hook import _validate_signature, extract_prompt, extract_summary


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

    def test_validate_signature_allows_when_secret_unset(self) -> None:
        os.environ.pop("CURSOR_WEBHOOK_SECRET", None)
        payload = {"event": "agent.update"}
        self.assertTrue(_validate_signature("{}", payload))

    def test_validate_signature_rejects_missing_signature_with_secret(self) -> None:
        os.environ["CURSOR_WEBHOOK_SECRET"] = "test-secret"
        os.environ.pop("CURSOR_WEBHOOK_SIGNATURE", None)
        payload = {"event": "agent.update"}
        self.assertFalse(_validate_signature("{}", payload))
        os.environ.pop("CURSOR_WEBHOOK_SECRET", None)

    def test_validate_signature_accepts_valid_hmac(self) -> None:
        secret = "test-secret"
        raw = '{"event":"agent.update","id":"abc"}'
        sig = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()

        os.environ["CURSOR_WEBHOOK_SECRET"] = secret
        os.environ["CURSOR_WEBHOOK_SIGNATURE"] = f"sha256={sig}"
        payload = {"event": "agent.update", "id": "abc"}
        self.assertTrue(_validate_signature(raw, payload))

        os.environ.pop("CURSOR_WEBHOOK_SECRET", None)
        os.environ.pop("CURSOR_WEBHOOK_SIGNATURE", None)


if __name__ == "__main__":
    unittest.main()
