#!/usr/bin/env python3
"""Unit tests for Antigravity plugin manifests and lifecycle hook contracts."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "claude-code" / "hooks"
ANTIGRAVITY_DIR = REPO_ROOT / "antigravity"

os.environ.setdefault("OBMEM_QUERY_IGNORE_FILE", os.devnull)
sys.path.insert(0, str(HOOKS_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"agy_test_{name}", HOOKS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


COMMON = _load("obsidian_hook_common")
START = _load("obsidian_sessionstart_hook")
PRE = _load("obsidian_preprompt_hook")
STOP = _load("obsidian_poststop_hook")


def _write_jsonl(entries: list[dict]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for entry in entries:
        handle.write(json.dumps(entry) + "\n")
    handle.close()
    return handle.name


class AntigravityCommonTests(unittest.TestCase):
    def test_detects_antigravity_camel_case_payloads(self) -> None:
        self.assertTrue(COMMON.is_antigravity_payload({
            "conversationId": "conv-1",
            "workspacePaths": ["/tmp/demo"],
            "hookEventName": "SessionStart",
        }))
        self.assertFalse(COMMON.is_antigravity_payload({
            "session_id": "sess-1",
            "cwd": "/tmp/demo",
            "hook_event_name": "SessionStart",
        }))

    def test_extract_user_request_unwraps_tags_and_metadata(self) -> None:
        raw = (
            "<USER_REQUEST>\nFix retry backoff in exporter.\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>\nLocal time: 2026-01-01\n</ADDITIONAL_METADATA>\n"
            "<USER_SETTINGS_CHANGE>\nModel switched.\n</USER_SETTINGS_CHANGE>"
        )
        self.assertEqual(COMMON.extract_user_request(raw), "Fix retry backoff in exporter.")
        self.assertEqual(COMMON.extract_user_request("Plain prompt text"), "Plain prompt text")

    def test_project_root_prefers_workspace_paths(self) -> None:
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
            with patch.object(COMMON, "_git_toplevel", return_value=None):
                root = COMMON.project_root({
                    "workspacePaths": ["/tmp/my-app"],
                    "cwd": "/tmp/my-app/subdir",
                })
        self.assertEqual(root, str(Path("/tmp/my-app").resolve()))

    def test_last_turn_parses_antigravity_transcript_and_edits(self) -> None:
        path = _write_jsonl([
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nFix retry queue limit\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {"name": "edit_file", "args": {"Path": '"/tmp/demo/queue.py"'}},
                    {"name": "write_file", "args": {"Path": "/tmp/demo/test_queue.py"}},
                ],
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Made 1 replacement.",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "content": "Updated queue retry limit to 3 and added unit tests.",
            },
        ])
        self.addCleanup(os.unlink, path)
        turn = COMMON.last_turn(path)
        self.assertEqual(turn["prompt"], "Fix retry queue limit")
        self.assertEqual(turn["assistant"], "Updated queue retry limit to 3 and added unit tests.")
        self.assertEqual(turn["edited_files"], ["/tmp/demo/queue.py", "/tmp/demo/test_queue.py"])
        self.assertEqual(turn["start_id"], "step-0")
        self.assertFalse(turn["recorded"])

    def test_last_turn_detects_successful_manual_record_run(self) -> None:
        path = _write_jsonl([
            {
                "step_index": 4,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nDocument the cache layout\n</USER_REQUEST>",
            },
            {
                "step_index": 5,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {"name": "edit_file", "args": {"Path": '"/tmp/demo/cache.py"'}},
                    {
                        "name": "run_command",
                        "args": {"CommandLine": '"obmem record-run --project demo --title Cache"'},
                    },
                ],
            },
            {
                "step_index": 6,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Command exited with code 0.\n\nCommand output:\nRecorded run note: Project Memory/demo/Runs/2026-01-01-cache.md",
            },
        ])
        self.addCleanup(os.unlink, path)
        turn = COMMON.last_turn(path)
        self.assertTrue(turn["recorded"])

    def test_last_turn_ignores_failed_record_run(self) -> None:
        path = _write_jsonl([
            {
                "step_index": 4,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nDocument the cache layout\n</USER_REQUEST>",
            },
            {
                "step_index": 5,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {"name": "edit_file", "args": {"Path": '"/tmp/demo/cache.py"'}},
                    {
                        "name": "run_command",
                        "args": {"CommandLine": '"obmem record-run --project demo --title Cache"'},
                    },
                ],
            },
            {
                "step_index": 6,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Command exited with code 1.\n\nCommand output:\nRecorded run note: failed",
            },
        ])
        self.addCleanup(os.unlink, path)
        turn = COMMON.last_turn(path)
        self.assertFalse(turn["recorded"])


class AntigravitySessionStartTests(unittest.TestCase):
    def test_healthy_vault_returns_antigravity_inject_steps_json(self) -> None:
        payload = {
            "conversationId": "conv-1",
            "workspacePaths": ["/tmp/demo"],
            "hookEventName": "SessionStart",
            "cwd": "/tmp/demo",
        }
        doctor = Mock(returncode=0, stdout="OK", stderr="")
        with patch.object(START, "active_context", return_value=("/tmp/demo", "demo")), \
             patch.object(START.subprocess, "run", return_value=doctor), \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(START.main(), 0)
        parsed = json.loads(out.getvalue())
        steps = parsed["injectSteps"]
        self.assertEqual(len(steps), 1)
        sys_msg = steps[0]["systemMessage"]
        self.assertIn("Vault healthy for demo", sys_msg["systemMessage"])
        self.assertIn("obsidian-cli-memory-bank", sys_msg["systemMessage"])
        self.assertNotIn("Skill tool", sys_msg["systemMessage"])
        self.assertEqual(sys_msg["metadata"]["user_markdown"], "Memory: vault healthy for demo.")

    def test_unmapped_workspace_returns_empty_json(self) -> None:
        payload = {
            "conversationId": "conv-1",
            "workspacePaths": ["/tmp/unmapped"],
            "hookEventName": "SessionStart",
        }
        with patch.object(START, "active_context", return_value=None), \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(START.main(), 0)
        self.assertEqual(json.loads(out.getvalue()), {})


class AntigravityPreInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pre_state = tempfile.TemporaryDirectory()
        self.stop_state = tempfile.TemporaryDirectory()
        self.addCleanup(self.pre_state.cleanup)
        self.addCleanup(self.stop_state.cleanup)
        self.env = patch.dict(os.environ, {
            "OBMEM_PREINVOCATION_STATE": self.pre_state.name,
            "OBMEM_STOP_STATE": self.stop_state.name,
            "OBMEM_QUERY_IGNORE_FILE": os.devnull,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def _run_pre(self, payload: dict, search_out: str, excerpt_out: str = "") -> dict:
        with patch.object(PRE, "active_context", return_value=("/tmp/demo", "demo")), \
             patch.object(PRE, "_search", side_effect=[search_out, ""]), \
             patch.object(PRE, "_vault_path", return_value=None), \
             patch.object(PRE, "_note_excerpts", return_value=excerpt_out), \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(PRE.main(), 0)
        return json.loads(out.getvalue())

    def test_injects_excerpts_once_per_turn_and_deduplicates_repeat_invocations(self) -> None:
        transcript = _write_jsonl([
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nWhy did we cap export retries at three?\n</USER_REQUEST>",
            }
        ])
        self.addCleanup(os.unlink, transcript)
        payload = {
            "conversationId": "conv-abc",
            "workspacePaths": ["/tmp/demo"],
            "transcriptPath": transcript,
            "hookEventName": "PreInvocation",
            "invocationNum": 1,
            "lastUserInput": "Why did we cap export retries at three?",
        }
        hit_output = "  Project Memory/demo/Decisions.md (score 10; Jev 0.85; best)"
        excerpt = "Excerpts:\n--- Project Memory/demo/Decisions.md ---\n# Decisions\nCap retries at 3."

        first = self._run_pre(payload, hit_output, excerpt)
        self.assertIn("injectSteps", first)
        msg = first["injectSteps"][0]["systemMessage"]
        self.assertIn("Cap retries at 3.", msg["systemMessage"])
        self.assertIn("Memory: read 1 of 1 matching notes: Decisions", msg["metadata"]["user_markdown"])

        # Second model call in the same turn (after a tool call) must no-op immediately.
        payload_second = {**payload, "invocationNum": 2}
        with patch.object(PRE, "_search") as mock_search, \
             patch("sys.stdin", io.StringIO(json.dumps(payload_second))), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(PRE.main(), 0)
        mock_search.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), {})

    def test_no_hits_returns_empty_json(self) -> None:
        payload = {
            "conversationId": "conv-empty",
            "workspacePaths": ["/tmp/demo"],
            "hookEventName": "PreInvocation",
            "invocationNum": 1,
            "lastUserInput": "Explain retry policy for background uploads",
        }
        result = self._run_pre(payload, "")
        self.assertEqual(result, {})


class AntigravityStopHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stop_state = tempfile.TemporaryDirectory()
        self.addCleanup(self.stop_state.cleanup)
        self.env = patch.dict(os.environ, {
            "OBMEM_STOP_STATE": self.stop_state.name,
            "OBMEM_STOP_LOG": "edits",
            "OBMEM_CAPTURE_IGNORE_FILE": os.devnull,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_logs_edited_turn_and_allows_stop(self) -> None:
        transcript = _write_jsonl([
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nAdd retry backoff config\n</USER_REQUEST>",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {"name": "edit_file", "args": {"Path": '"/tmp/demo/retry.py"'}},
                ],
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "content": "Added exponential retry backoff in retry.py.",
            },
        ])
        self.addCleanup(os.unlink, transcript)
        payload = {
            "conversationId": "conv-stop-1",
            "workspacePaths": ["/tmp/demo"],
            "transcriptPath": transcript,
            "hookEventName": "Stop",
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
        }
        ok = subprocess.CompletedProcess(["obmem"], 0, "Recorded run note: x\n", "")
        with patch.object(STOP, "active_context", return_value=("/tmp/demo", "demo")), \
             patch.object(STOP, "record_run", return_value=ok) as mock_rec, \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as out, \
             patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(STOP.main(), 0)
        self.assertEqual(json.loads(out.getvalue()), {"decision": "allow"})
        mock_rec.assert_called_once()
        kwargs = mock_rec.call_args.kwargs
        self.assertEqual(kwargs["tags"], "antigravity,auto-log")
        self.assertIn("Antigravity Stop event", kwargs["actions"])
        self.assertEqual(kwargs["session"], "conv-stop-1")

        # Second Stop for the same turn is deduplicated.
        with patch.object(STOP, "active_context", return_value=("/tmp/demo", "demo")), \
             patch.object(STOP, "record_run", return_value=ok) as mock_rec2, \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as out2:
            self.assertEqual(STOP.main(), 0)
        mock_rec2.assert_not_called()
        self.assertEqual(json.loads(out2.getvalue()), {"decision": "allow"})

    def test_skips_canceled_and_errored_stops(self) -> None:
        for reason in ("USER_CANCELED", "ERROR"):
            payload = {
                "conversationId": "conv-cancel",
                "workspacePaths": ["/tmp/demo"],
                "hookEventName": "Stop",
                "terminationReason": reason,
            }
            with patch.object(STOP, "record_run") as mock_rec, \
                 patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                 patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(STOP.main(), 0)
            mock_rec.assert_not_called()
            self.assertEqual(json.loads(out.getvalue()), {"decision": "allow"})


class AntigravityPluginBundleTests(unittest.TestCase):
    def test_plugin_and_hooks_manifests_are_valid_json(self) -> None:
        plugin = json.loads((ANTIGRAVITY_DIR / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "obsidian-cli-memory-bank")
        self.assertLessEqual(len(plugin.get("suggestedPrompts", [])), 3)

        hooks = json.loads((ANTIGRAVITY_DIR / "hooks.json").read_text(encoding="utf-8"))
        spec = hooks["obsidian-memory"]
        for event in ("SessionStart", "PreInvocation", "Stop"):
            self.assertIsInstance(spec[event], list)
            self.assertTrue(spec[event])
            for handler in spec[event]:
                self.assertEqual(handler.get("type"), "command")
                self.assertIn("run_hook.py", handler.get("command", ""))

        skill_md = ANTIGRAVITY_DIR / "skills" / "obsidian-cli-memory-bank" / "SKILL.md"
        self.assertTrue(skill_md.is_file())
        self.assertIn("name: obsidian-cli-memory-bank", skill_md.read_text(encoding="utf-8"))

    def test_run_hook_launcher_dispatches_and_returns_valid_json(self) -> None:
        launcher = ANTIGRAVITY_DIR / "hooks" / "run_hook.py"
        env = {**os.environ, "OBMEM_HOOKS": "off"}
        for hook_name, payload, expected in (
            ("sessionstart", {"conversationId": "c1", "hookEventName": "SessionStart", "cwd": "/tmp"}, {}),
            ("preprompt", {"conversationId": "c1", "hookEventName": "PreInvocation", "lastUserInput": "hello world test"}, {}),
            ("poststop", {"conversationId": "c1", "hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL"}, {"decision": "allow"}),
        ):
            proc = subprocess.run(
                [sys.executable, str(launcher), hook_name],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), expected)


if __name__ == "__main__":
    unittest.main()
