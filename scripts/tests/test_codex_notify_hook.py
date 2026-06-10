#!/usr/bin/env python3
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

from scripts.codex_notify_hook import (
    _resolve_skill_repo_from_argv,
    extract_prompt,
    extract_summary,
    slug_to_title,
    truncate,
)


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

    def test_resolve_skill_repo_from_argv(self) -> None:
        self.assertEqual(
            _resolve_skill_repo_from_argv(["--skill-repo", "."]),
            Path(".").resolve(),
        )
        self.assertEqual(
            _resolve_skill_repo_from_argv(["--skill-repo=."]),
            Path(".").resolve(),
        )

    def test_import_from_copied_hook_with_skill_repo_arg(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        source_hook = repo_root / "scripts" / "codex_notify_hook.py"

        old_argv = sys.argv[:]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                copied_hook = Path(tmpdir) / "obsidian_memory_notify.py"
                shutil.copy(source_hook, copied_hook)
                sys.argv = [str(copied_hook), "--skill-repo", str(repo_root), "{}"]
                spec = importlib.util.spec_from_file_location("copied_codex_notify_hook", copied_hook)
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(
                    module.extract_summary({"last-assistant-message": "Copied hook works."}),
                    "Copied hook works.",
                )
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
