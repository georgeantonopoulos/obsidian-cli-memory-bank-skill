import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = Path(__file__).resolve().parents[2] / "claude-code" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


HOOK = _load("obsidian_preprompt_hook")
COMMON = _load("obsidian_hook_common")
STOP = _load("obsidian_poststop_hook")
SYNC = _load("obsidian_memory_sync_hook")

FAKE_KEY = "apikey_" + "0123456789abcdef" * 2 + "_" + "fedcba9876543210" * 4


class ClaudePrePromptHookTests(unittest.TestCase):
    def test_select_search_hits_caps_ranked_output(self) -> None:
        output = """Found 5 hits.
  Project Memory/demo/Current Memory.md (score 9)
  Project Memory/demo/Topics/Rendering.md (score 8)
  Project Memory/demo/Decisions.md (score 7)
  Project Memory/demo/Runs/old-run.md (score 6)
  Project Memory/demo/Run Log.md (score 5)
"""

        selected = HOOK._select_search_hits(output)

        self.assertIn("Showing top 3 relevant note(s):", selected)
        self.assertIn("Current Memory.md", selected)
        self.assertIn("Topics/Rendering.md", selected)
        self.assertIn("Decisions.md", selected)
        self.assertNotIn("old-run.md", selected)
        self.assertNotIn("Run Log.md", selected)

    def test_select_search_hits_handles_no_matches(self) -> None:
        self.assertEqual(HOOK._select_search_hits("No matches found."), "")

    def test_select_search_hits_keeps_jev_order(self) -> None:
        output = """Found 12 hits; showing 3. Ranked by Jev.
  Project Memory/demo/Compactions/2026-06-18-compact.md (score 160; Jev 0.91; best)
  Project Memory/demo/Topics/Search.md (score 120; Jev 0.70)
  Project Memory/demo/Current Memory.md (score 110; Jev 0.40)
"""
        lines = HOOK._select_search_hits(output).splitlines()[1:]
        self.assertIn("Compactions/2026-06-18", lines[0])
        self.assertIn("Topics/Search.md", lines[1])

    def test_local_order_demotes_compactions(self) -> None:
        output = """Found 3 hits; showing 3.
  Project Memory/demo/Compactions/2026-06-18-compact.md (score 160)
  Project Memory/demo/Topics/Search.md (score 120)
  Project Memory/demo/Current Memory.md (score 110)
"""
        lines = HOOK._select_search_hits(output).splitlines()[1:]
        self.assertIn("Topics/Search.md", lines[0])
        self.assertIn("Compactions/2026-06-18", lines[2])

    def test_jev_gate_keeps_the_hook_quiet(self) -> None:
        gated = "Found 9 hits; none cleared the Jev threshold 0.30 (best 0.04)."
        payload = json.dumps({"prompt": "What is a good moussaka recipe with aubergine?", "cwd": tempfile.gettempdir()})
        completed = HOOK.subprocess.CompletedProcess([], 0, gated, "")
        with patch("sys.stdin") as stdin, patch.object(HOOK, "active_context", return_value=("/w", "demo")), \
                patch.object(HOOK.subprocess, "run", return_value=completed) as run, \
                patch("sys.stdout", new_callable=__import__("io").StringIO) as stdout:
            stdin.read.return_value = payload
            self.assertEqual(HOOK.main(), 0)
        self.assertEqual(stdout.getvalue(), "")
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("--min-jev") + 1], "0.30")

    def test_jev_min_env_override_is_clamped(self) -> None:
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "0.5"}):
            self.assertEqual(HOOK._jev_min(), 0.5)
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "7"}):
            self.assertEqual(HOOK._jev_min(), 1.0)
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "nope"}):
            self.assertEqual(HOOK._jev_min(), 0.30)

    def test_sanitize_query_never_searches_secrets(self) -> None:
        query = HOOK._sanitize_query(f"Use this key {FAKE_KEY} for Jev ranking")
        self.assertNotIn("0123456789abcdef", query)
        self.assertNotIn("apikey", query)
        self.assertIn("jev", query.split())

    def test_sanitize_query_prefers_named_things_over_filler(self) -> None:
        query = HOOK._sanitize_query("Ok anything obvious to improve with this obmem skill or `set-search-ranker` and Jev?")
        words = query.split()
        self.assertIn("jev", words)
        self.assertIn("ranker", words)
        for filler in ("anything", "obvious", "improve"):
            self.assertNotIn(filler, words)

    def test_sanitize_query_ignores_capitalised_sentence_starts(self) -> None:
        query = HOOK._sanitize_query("Please check the Nuke gizmo. Colour pipeline broke in OKLCH")
        self.assertEqual(set(query.split()[:2]), {"nuke", "oklch"})


class HookCommonTests(unittest.TestCase):
    def test_redact_secrets_covers_common_shapes(self) -> None:
        text = (
            f"key {FAKE_KEY} and sk-ant-{'a1' * 20} and Authorization: Bearer {'x9' * 12} "
            "TYPESAFE_API_KEY=supersecretvalue1"
        )
        redacted = COMMON.redact_secrets(text)
        for secret in (FAKE_KEY, "a1a1a1a1", "x9x9x9x9", "supersecretvalue1"):
            self.assertNotIn(secret, redacted)
        self.assertIn("TYPESAFE_API_KEY=", redacted)

    def test_redact_secrets_keeps_note_slugs_and_uuids(self) -> None:
        text = "Runs/2026-01-02-0304-retry-queue-fix-for-export-worker.md 123e4567-e89b-12d3-a456-426614174000"
        self.assertEqual(COMMON.redact_secrets(text), text)

    def test_project_root_prefers_launch_dir_over_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "vault" / "Project Memory"
            sub.mkdir(parents=True)
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": tmp}):
                self.assertEqual(COMMON.project_root({"cwd": str(sub)}), str(Path(tmp).resolve()))
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
                self.assertEqual(COMMON.project_root({"cwd": str(sub)}), str(sub.resolve()))

    def test_hooks_disabled_by_env_or_marker_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OBMEM_HOOKS": ""}):
                self.assertFalse(COMMON.hooks_disabled(tmp))
                (Path(tmp) / ".obmem-off").touch()
                self.assertTrue(COMMON.hooks_disabled(tmp))
            with patch.dict(os.environ, {"OBMEM_HOOKS": "off"}):
                self.assertTrue(COMMON.hooks_disabled(tempfile.gettempdir()))

    def _transcript(self, entries):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_last_turn_reads_prompt_reply_and_edits(self) -> None:
        path = self._transcript([
            {"type": "user", "message": {"content": "old prompt"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "old reply"}]}},
            {"type": "user", "message": {"content": "fix the export hook"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/b.py"}},
            ]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed it."}]}},
        ])
        turn = COMMON.last_turn(path)
        self.assertEqual(turn["prompt"], "fix the export hook")
        self.assertEqual(turn["assistant"], "Fixed it.")
        self.assertEqual(turn["edited_files"], ["/b.py"])

    def test_recent_prompts_skip_tool_results_and_meta(self) -> None:
        path = self._transcript([
            {"type": "user", "message": {"content": "first"}},
            {"type": "user", "isMeta": True, "message": {"content": "meta"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
            {"type": "user", "message": {"content": "second"}},
        ])
        self.assertEqual(COMMON.recent_prompts(path), ["first", "second"])


class StopHookTests(unittest.TestCase):
    def test_question_only_turns_are_not_logged_by_default(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "what is obmem?"}}) + "\n")
        self.addCleanup(os.unlink, handle.name)
        payload = json.dumps({"transcript_path": handle.name, "cwd": tempfile.gettempdir()})
        with patch.dict(os.environ, {"OBMEM_STOP_LOG": ""}), patch("sys.stdin") as stdin, \
                patch.object(STOP, "record_run") as record_run:
            stdin.read.return_value = payload
            self.assertEqual(STOP.main(), 0)
            record_run.assert_not_called()


class MemorySyncHookTests(unittest.TestCase):
    def test_only_claude_auto_memory_paths_sync(self) -> None:
        self.assertTrue(SYNC._is_memory_path("/Users/me/.claude/projects/-Users-me-Dev-X/memory/user-role.md"))
        self.assertTrue(SYNC._is_memory_path("/Users/me/.claude/projects/-Users-me-Dev-X/memory/MEMORY.md"))
        self.assertFalse(SYNC._is_memory_path("/Users/me/Dev/app/src/memory/cache.md"))
        self.assertFalse(SYNC._is_memory_path("/Users/me/Dev/app/GPU_MEMORY.md"))


if __name__ == "__main__":
    unittest.main()
