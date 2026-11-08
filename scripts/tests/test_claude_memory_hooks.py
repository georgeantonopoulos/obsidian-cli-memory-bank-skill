import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock
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
START = _load("obsidian_sessionstart_hook")

FAKE_KEY = "apikey_" + "0123456789abcdef" * 2 + "_" + "fedcba9876543210" * 4


class ClaudeSessionStartHookTests(unittest.TestCase):
    def _run(self, doctor_returncode: int) -> str:
        doctor = unittest.mock.Mock(returncode=doctor_returncode, stdout="", stderr="vault offline")
        with patch.object(START, "read_payload", return_value={"cwd": "/tmp/demo"}), \
             patch.object(START, "active_context", return_value=("/tmp/demo", "demo")), \
             patch.object(START.subprocess, "run", return_value=doctor), \
             patch("sys.stdin"), patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
            self.assertEqual(START.main(), 0)
        return out.getvalue()

    def test_requires_loading_the_skill_when_vault_is_healthy(self) -> None:
        output = self._run(0)
        self.assertIn("Vault healthy for demo", output)
        self.assertIn('MANDATORY', output)
        self.assertIn('skill "obsidian-cli-memory-bank"', output)
        self.assertIn('obmem record-run --project "demo"', output)
        self.assertIn("including work done only in a browser", output)

    def test_requires_loading_the_skill_when_health_check_fails(self) -> None:
        output = self._run(1)
        self.assertIn("WARNING", output)
        self.assertIn('skill "obsidian-cli-memory-bank"', output)


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

    def test_ranker_order_kept_and_run_notes_not_buried(self) -> None:
        output = """Found 12 hits; showing 4. Ranked by Jev.
  Project Memory/demo/Runs/2026-06-18-0900-fix-export.md (score 160; Jev 0.91; best)
  Project Memory/demo/Topics/Search.md (score 120; Jev 0.70)
  Project Memory/demo/Current Memory.md (score 110; Jev 0.80)
  Project Memory/demo/Runs/2026-06-19-0900-memory-sync-notes-md-demo.md (score 100; Jev 0.95)
"""
        lines = HOOK._select_search_hits(output).splitlines()[1:]
        self.assertIn("fix-export", lines[0])
        self.assertIn("Topics/Search.md", lines[1])
        self.assertIn("Current Memory.md", lines[2])
        self.assertFalse(any("memory-sync" in line for line in lines))

    def test_moc_and_run_log_go_behind_the_run_they_list(self) -> None:
        # Pixel's 7 Nov slip: the MOC listing the "$0 sale" run was injected instead of the run.
        output = """Found 4 hits; showing 4. Ranked by Jev.
  Project Memory/google-watch/MOC.md (score 300; Jev 0.90)
  Project Memory/google-watch/Run Log.md (score 290; Jev 0.88)
  Project Memory/google-watch/Runs/2026-11-05-0558-testers-community-0-sale-scheduled.md (score 272; Jev 0.95; best)
  Project Memory/google-watch/Decisions.md (score 250; Jev 0.60)
"""
        lines = HOOK._select_search_hits(output).splitlines()[1:]
        self.assertIn("0-sale-scheduled", lines[0])
        self.assertIn("Decisions.md", lines[1])
        self.assertIn("MOC.md", lines[2])
        self.assertFalse(any("Run Log.md" in line for line in lines))

    def test_local_order_demotes_compactions(self) -> None:
        output = """Found 3 hits; showing 3.
  Project Memory/demo/Compactions/2026-06-18-compact.md (score 160)
  Project Memory/demo/Topics/Search.md (score 120)
  Project Memory/demo/Current Memory.md (score 110)
"""
        lines = HOOK._select_search_hits(output).splitlines()[1:]
        self.assertIn("Topics/Search.md", lines[0])
        self.assertIn("Compactions/2026-06-18", lines[2])

    def test_recency_questions_are_recognised(self) -> None:
        for prompt in ("What projects did we recently work on?", "what have we done lately",
                       "anything from yesterday?", "what did we work on last week"):
            self.assertTrue(HOOK._is_recency_question(prompt), prompt)
        for prompt in ("Why does Export progress jump around?", "fix the tracker search box",
                       "fix the recent regression in Foo", "the bug I worked on in the viewer",
                       "the last time the cache invalidated, why?", "yesterday's build failed",
                       "what did we work on lately? " + "word " * 40):
            self.assertFalse(HOOK._is_recency_question(prompt), prompt)

    def test_recency_lists_newest_sessions_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            notes = {
                "alpha/Runs/2026-06-01-0900-old-thing.md": "# Old thing\n",
                "alpha/Runs/2026-06-03-1015-new-thing.md": "---\ntitle: x\n---\n# New thing\n",
                "beta/Runs/2026-06-02-1200-middle.md": "# Middle\n",
                "beta/Runs/2026-06-04-0800-memory-sync-notes-md-beta.md": "# Memory sync\n",
                "beta/Topics/Search.md": "# Not a session\n",
                "alpha/Runs/2026-06-02-1300-new-thing.md": "# New thing\n",
                "beta/Runs/2026-06-02-1100-turn-a.md": "# beta Turn 01a0ad40-268d-7e62-8a80-365ee8cb6bbb Middle\n",
            }
            for rel, body in notes.items():
                path = vault / "Project Memory" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            bad = vault / "Project Memory" / "beta" / "Runs" / "2026-06-01-0800-latin1.md"
            bad.write_bytes(b"# caf\xe9 \xff\n")
            secret = vault / "Project Memory" / "beta" / "Runs" / "2026-06-01-0700-key.md"
            secret.write_text(f"# use {FAKE_KEY} here\n", encoding="utf-8")
            listed = HOOK._recent_sessions(vault, limit=10)
            self.assertTrue(any(title.startswith("caf") for _when, _proj, title in listed))
            self.assertFalse(any(FAKE_KEY[:20] in title for _when, _proj, title in listed))
            sessions = HOOK._recent_sessions(vault, limit=2)
            self.assertEqual(sessions, [("2026-06-03 10:15", "alpha", "New thing"),
                                        ("2026-06-02 12:00", "beta", "Middle")])

            payload = json.dumps({"prompt": "what did we work on lately?", "cwd": tmp})
            with patch("sys.stdin") as stdin, patch.object(HOOK, "active_context", return_value=("/w", "demo")), \
                    patch.object(HOOK, "_vault_path", return_value=vault), \
                    patch.object(HOOK.subprocess, "run") as run, \
                    patch("sys.stdout", new_callable=__import__("io").StringIO) as stdout:
                stdin.read.return_value = payload
                self.assertEqual(HOOK.main(), 0)
            run.assert_not_called()
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["systemMessage"], "Memory: listed recent work across 2 projects")
            context = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Projects by latest session: alpha (2026-06-03), beta (2026-06-02)", context)
            self.assertLess(context.index("New thing"), context.index("Old thing"))
            self.assertEqual(context.count("New thing"), 1)
            self.assertEqual(context.count("Middle"), 1)

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
        self.assertEqual(argv[argv.index("--min-jev") + 1], "0.50")

    def test_search_output_carries_the_end_of_turn_recording_rule(self) -> None:
        payload = json.dumps({"prompt": "Why does the compositor viewer flicker on resize?", "cwd": tempfile.gettempdir()})
        completed = HOOK.subprocess.CompletedProcess([], 0, "No matches found.", "")
        with patch("sys.stdin") as stdin, patch.object(HOOK, "active_context", return_value=("/w", "demo")), \
                patch.object(HOOK.subprocess, "run", return_value=completed), \
                patch("sys.stdout", new_callable=__import__("io").StringIO) as stdout:
            stdin.read.return_value = payload
            self.assertEqual(HOOK.main(), 0)
        self.assertIn("No matches.", stdout.getvalue())
        self.assertIn('obmem record-run --project "demo"', stdout.getvalue())

    def test_clean_excerpt_drops_frontmatter_nav_and_related(self) -> None:
        note = """---
type: "run"
---

# Fix export

Parent note: [[Home]]
MOC: [[MOC]]

## Summary
Progress uses measured counts.



## Related
- [[Other]]

[Excerpt: characters 0:300 of 900. use --offset 300 to continue.]
"""
        excerpt = HOOK._clean_excerpt(note)
        self.assertTrue(excerpt.startswith("# Fix export"))
        self.assertIn("Progress uses measured counts.", excerpt)
        for gone in ("type:", "Parent note", "MOC:", "Related", "[Excerpt", "\n\n\n"):
            self.assertNotIn(gone, excerpt)
        self.assertEqual(len(HOOK._clean_excerpt("x" * 5000, 100)), 100)

    def test_top_notes_are_injected_as_excerpts(self) -> None:
        search = """Found 3 hits; showing 3. Ranked by Jev.
  Project Memory/demo/Topics/Export.md (score 9; Jev 0.9; best)
  Project Memory/demo/Topics/Render.md (score 8; Jev 0.8)
  Project Memory/demo/Topics/Other.md (score 7; Jev 0.7)
"""
        def fake_run(argv, **_kwargs):
            if argv[1] == "search":
                return HOOK.subprocess.CompletedProcess(argv, 0, search, "")
            path = argv[argv.index("--path") + 1]
            return HOOK.subprocess.CompletedProcess(argv, 0, f"# {path}\nbody of {path}\n", "")

        payload = json.dumps({"prompt": "Why does Export progress jump around?", "cwd": tempfile.gettempdir()})
        with patch("sys.stdin") as stdin, patch.object(HOOK, "active_context", return_value=("/w", "demo")), \
                patch.object(HOOK.subprocess, "run", side_effect=fake_run) as run, \
                patch("sys.stdout", new_callable=__import__("io").StringIO) as stdout:
            stdin.read.return_value = payload
            self.assertEqual(HOOK.main(), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["systemMessage"], "Memory: read 2 of 3 matching notes: Project Memory/demo/Topics/Export.md; Project Memory/demo/Topics/Render.md")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        out = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("body of Project Memory/demo/Topics/Export.md", out)
        self.assertIn("body of Project Memory/demo/Topics/Render.md", out)
        self.assertNotIn("body of Project Memory/demo/Topics/Other.md", out)
        self.assertEqual(run.call_count, 3)

    def test_jev_min_env_override_is_clamped(self) -> None:
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "0.5"}):
            self.assertEqual(HOOK._jev_min(), 0.5)
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "7"}):
            self.assertEqual(HOOK._jev_min(), 1.0)
        with patch.dict(os.environ, {"OBMEM_JEV_MIN": "nope"}):
            self.assertEqual(HOOK._jev_min(), 0.50)

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


    def _office(self, names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        roster = {f"/p/{i}": {"name": name} for i, name in enumerate(names)}
        (Path(tmp.name) / "leads.json").write_text(json.dumps(roster))
        return patch.dict(os.environ, {"OBMEM_OFFICE_DIR": tmp.name, "OBMEM_OFFICE_NAMES": ""})

    def test_office_message_searches_the_topic_not_the_people(self) -> None:
        prompt = ('Another Claude session sent a message:\n<cross-session-message from="uds:/tmp/x.sock" '
                  'from-name="Gary" from-mode="prompting">\nPixel: George wants testers on Dew Drop for '
                  'free, set up the free tester sale. SendMessage me when done.</cross-session-message>')
        with self._office(["Pixel Pete", "Cleo Clang"]):
            words = HOOK._sanitize_query(prompt).split()
        self.assertIn("sale", words)
        for noise in ("gary", "george", "pixel", "sendmessage", "cross", "session", "message", "uds"):
            self.assertNotIn(noise, words)

    def test_roster_names_dropped_only_when_written_as_names(self) -> None:
        with self._office(["Merge Margaret", "Pixel Pete"]):
            words = HOOK._sanitize_query("Merge the loader branch. Ask Margaret about the pixel shader").split()
        self.assertIn("pixel", words)
        self.assertNotIn("margaret", words)

    def test_money_and_version_tokens_survive(self) -> None:
        with self._office([]):
            words = HOOK._sanitize_query("Create a $0 sale on Dew Drop so testers get it free").split()
            self.assertIn("$0", words)
            self.assertIn("sale", words)
            words = HOOK._sanitize_query("[Scheduled: Sequency 1.5 App Store review] check Gmail").split()
            self.assertIn("1.5", words)
            self.assertNotIn("scheduled", words)
            self.assertNotIn("2", HOOK._sanitize_query("fix 2 bugs in the export queue").split())

    def test_missing_roster_fails_open(self) -> None:
        with patch.dict(os.environ, {"OBMEM_OFFICE_DIR": "/nonexistent/obmem-office"}):
            self.assertIn("nuke", HOOK._sanitize_query("George: the Nuke gizmo colour pipeline broke").split())


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

    def test_office_message_starts_its_own_turn(self) -> None:
        # Gary's 7 Nov note paired "Cody seems stuck?" with the reply to a later message from Cody.
        path = self._transcript([
            {"type": "user", "uuid": "u1", "origin": {"kind": "human"}, "message": {"content": "Cody seems stuck?"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/notes.md"}},
                {"type": "text", "text": "Asked Cody."}]}},
            {"type": "user", "uuid": "u2", "isMeta": True,
             "origin": {"kind": "peer", "name": "Cody", "body": "Glimmerwild final"},
             "message": {"content": 'Another Claude session sent a message:\n<cross-session-message from="x">'
                                    "Glimmerwild final</cross-session-message>"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Glimmerwild 1.0.0 is finished."}]}},
        ])
        turn = COMMON.last_turn(path)
        self.assertEqual(turn["prompt"], "Message from Cody: Glimmerwild final")
        self.assertEqual(turn["assistant"], "Glimmerwild 1.0.0 is finished.")
        self.assertEqual(turn["edited_files"], [])
        self.assertEqual(turn["start_id"], "u2")

    def test_task_notice_and_typed_office_prompts_start_turns(self) -> None:
        notice = ("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n"
                  "<summary>Background command \"make test\" completed (exit code 0)</summary>\n</task-notification>")
        path = self._transcript([
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": "[Scheduled: Daily brief] read mail"}},
            {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": notice}},
        ])
        self.assertEqual(COMMON.last_turn(path)["prompt"],
                         'Background task: Background command "make test" completed (exit code 0)')

    def test_skill_and_reminder_meta_entries_do_not_start_turns(self) -> None:
        path = self._transcript([
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": "fix export"}},
            {"type": "user", "isMeta": True, "message": {"content": "Base directory for this skill: x"}},
            {"type": "user", "isMeta": True, "message": {"content": "<system-reminder>x</system-reminder>"}},
        ])
        self.assertEqual(COMMON.last_turn(path)["prompt"], "fix export")

    def test_message_arriving_mid_turn_stays_part_of_that_turn(self) -> None:
        notice = "<task-notification><summary>Background command done</summary></task-notification>"
        path = self._transcript([
            {"type": "user", "uuid": "u1", "origin": {"kind": "human"}, "message": {"content": "fix export"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": notice}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/b.py"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
        ])
        turn = COMMON.last_turn(path)
        self.assertEqual(turn["prompt"], "fix export")
        self.assertEqual(turn["edited_files"], ["/a.py", "/b.py"])

    def test_interrupt_and_meta_entries_never_start_turns(self) -> None:
        path = self._transcript([
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": "fix export"}},
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": "[Request interrupted by user]"}},
            {"type": "user", "origin": {"kind": "human"}, "isMeta": True, "message": {"content": "<local-command-caveat>x"}},
        ])
        self.assertEqual(COMMON.last_turn(path)["prompt"], "fix export")

    def test_odd_transcript_shapes_do_not_crash(self) -> None:
        path = self._transcript([
            {"type": "user", "message": "not a dict"},
            {"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": ["x"]}, {"type": "text", "text": None}, "junk"]}},
        ])
        self.assertEqual(COMMON.last_turn(path)["prompt"], "go")

    def test_last_turn_notices_a_manual_record_run(self) -> None:
        path = self._transcript([
            {"type": "user", "message": {"content": "ship it"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": 'obmem record-run --project "X" --title t'}}]}},
        ])
        self.assertTrue(COMMON.last_turn(path)["recorded"])


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

    def _run_stop(self, entries, session="s1"):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        payload = json.dumps({"transcript_path": handle.name, "session_id": session, "cwd": tempfile.gettempdir()})
        ok = __import__("subprocess").CompletedProcess([], 0, "", "")
        with patch("sys.stdin") as stdin, patch.object(STOP, "record_run", return_value=ok) as record_run, \
                patch.object(STOP, "active_context", return_value=("/w", "Demo")):
            stdin.read.return_value = payload
            STOP.main()
        return record_run

    def _state(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return patch.dict(os.environ, {"OBMEM_STOP_LOG": "", "OBMEM_STOP_STATE": str(Path(tmp.name) / "seen.json")})

    EDIT_TURN = [
        {"type": "user", "uuid": "u1", "origin": {"kind": "human"}, "message": {"content": "fix the export hook"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/b.py"}},
            {"type": "text", "text": "Fixed."}]}},
    ]

    def test_same_turn_is_logged_once_even_if_stop_fires_again(self) -> None:
        with self._state():
            self.assertEqual(self._run_stop(self.EDIT_TURN).call_count, 1)
            # An unrecognised wake (e.g. a relay) adds no new turn start: no second note.
            later = self.EDIT_TURN + [
                {"type": "user", "isMeta": True, "message": {"content": "<relay from=\"c\">ping</relay>"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
            ]
            self.assertEqual(self._run_stop(later).call_count, 0)
            # Another session's turn with the same start id is still logged.
            self.assertEqual(self._run_stop(self.EDIT_TURN, session="s2").call_count, 1)

    def test_office_reply_after_edit_turn_is_not_relogged(self) -> None:
        with self._state():
            self._run_stop(self.EDIT_TURN)
            later = self.EDIT_TURN + [
                {"type": "user", "uuid": "u2", "isMeta": True, "origin": {"kind": "peer", "name": "Gary", "body": "status?"},
                 "message": {"content": "Another Claude session sent a message: status?"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "All done."}]}},
            ]
            self.assertEqual(self._run_stop(later).call_count, 0)

    def test_turn_that_ran_record_run_is_not_auto_logged(self) -> None:
        turn = self.EDIT_TURN + [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "obmem record-run --project Demo --title x"}}]}}]
        with self._state():
            self.assertEqual(self._run_stop(turn).call_count, 0)


class MemorySyncHookTests(unittest.TestCase):
    def test_only_claude_auto_memory_paths_sync(self) -> None:
        self.assertTrue(SYNC._is_memory_path("/Users/me/.claude/projects/-Users-me-Dev-X/memory/user-role.md"))
        self.assertTrue(SYNC._is_memory_path("/Users/me/.claude/projects/-Users-me-Dev-X/memory/MEMORY.md"))
        self.assertFalse(SYNC._is_memory_path("/Users/me/Dev/app/src/memory/cache.md"))
        self.assertFalse(SYNC._is_memory_path("/Users/me/Dev/app/GPU_MEMORY.md"))


if __name__ == "__main__":
    unittest.main()
