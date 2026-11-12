#!/usr/bin/env python3
import argparse
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.obsidian_memory import (
    DEFAULT_AUDIT_EVERY_RUNS,
    PROJECTS_INDEX_PATH,
    _append_to_related_section,
    _build_or_query,
    _build_topics,
    _collect_uncompacted_runs,
    _search_priority,
    _contains_cli_error,
    _extract_wikilinks,
    _has_link_to,
    _merge_run_history,
    _plan_archive_destinations,
    _related_entry,
    _parse_related_arg,
    _parse_search_output_paths,
    cmd_compact_project,
    ConfigStore,
    ObsidianCLI,
    build_parser,
    build_note_paths,
    build_seed_notes,
    bootstrap_project,
    ensure_project_dirs,
    ensure_projects_index,
    ensure_related_link,
    parse_tags,
    resolve_note_path,
    RunMemory,
    sanitize_note_title_component,
    slugify,
    weave_bidirectional,
)


class ObsidianMemoryTests(unittest.TestCase):
    def test_audit_checks_qualified_target_not_another_projects_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            home = vault / "Project Memory/demo"
            home.mkdir(parents=True)
            (home / "MOC.md").write_text("# MOC\n")
            (home / "source.md").write_text(
                "[[Project Memory/demo/MOC|valid]]\n"
                "[[Project Memory/missing/MOC|missing]]\n"
            )
            output = ObsidianCLI(vault, False).audit_unresolved(verbose=False)
            self.assertIn("1 unresolved link target", output)
            self.assertIn("Project Memory/missing/MOC", output)
            self.assertNotIn("Project Memory/demo/MOC", output)

    def test_compaction_collision_preserves_both_sources_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Demo")
            for directory in (paths.runs_dir, paths.archived_runs_dir):
                (vault / directory).mkdir(parents=True)
            template = '---\ntype: "run"\nproject: "Demo"\ntags: [export]\n---\n\n## Summary\n{}\n'
            old = vault / paths.archived_runs_dir / "shared.md"
            source = vault / paths.runs_dir / "shared.md"
            old.write_text(template.format("Preserve the Linux export configuration."))
            source.write_text(template.format("Use measured frame counts for Windows exports."))
            args = build_parser().parse_args(["compact-project", "--project", "Demo"])
            with patch("scripts.obsidian_memory.resolve_vault_or_exit", return_value=vault), contextlib.redirect_stdout(io.StringIO()):
                cmd_compact_project(args)
            self.assertFalse(source.exists())
            moved = vault / paths.archived_runs_dir / "shared-2.md"
            self.assertIn("Windows exports", moved.read_text())
            self.assertIn("Linux export", old.read_text())
            compaction = next((vault / paths.compactions_dir).glob("*.md")).read_text()
            self.assertIn("[[Project Memory/demo/Archive/Runs/shared|", compaction)
            self.assertIn("[[Project Memory/demo/Archive/Runs/shared-2|", compaction)

    def test_qualified_weave_is_idempotent_and_unlink_preserves_other_project(self) -> None:
        from scripts.obsidian_memory import unweave_bidirectional
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            source = Path("Project Memory/demo/Runs/run.md")
            topic = Path("Project Memory/demo/Topics/Audio.md")
            for path in (source, topic):
                (vault / path).parent.mkdir(parents=True, exist_ok=True)
                (vault / path).write_text("# Note\n")
            cli = ObsidianCLI(vault, dry_run=False)
            weave_bidirectional(cli, source, [topic])
            once = (vault / source).read_text()
            weave_bidirectional(cli, source, [topic])
            self.assertEqual(once, (vault / source).read_text())
            foreign = "- [[Project Memory/other/Topics/Audio|Audio]]\n"
            evidence = "\n## Sources\n- [[Project Memory/demo/Topics/Audio|Audio]]\n"
            (vault / source).write_text(once + foreign + evidence)
            unweave_bidirectional(cli, source, [topic])
            after = (vault / source).read_text()
            self.assertIn(foreign, after)
            self.assertIn(evidence, after)
            self.assertNotIn("Project Memory/demo/Runs/run", (vault / topic).read_text())

    def test_resolve_qualified_alias_and_reject_ambiguous_short_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Demo")
            for directory in (paths.runs_dir, paths.archived_runs_dir):
                (vault / directory).mkdir(parents=True)
                (vault / directory / "shared.md").write_text("source")
            self.assertIsNone(resolve_note_path(vault, paths, "shared"))
            self.assertEqual(resolve_note_path(vault, paths, "[[Project Memory/demo/Runs/shared|source]]"), paths.runs_dir / "shared.md")

    def test_merge_history_keeps_same_stem_from_distinct_paths(self) -> None:
        def run(path: str) -> RunMemory:
            return RunMemory(Path(path), Path(path).stem, "x", "2026", [], "", "", "", "", "", [])

        merged = _merge_run_history(
            [run("Project Memory/a/Archive/Runs/shared.md")],
            [run("Project Memory/a/Runs/shared.md")],
        )
        self.assertEqual({item.path.as_posix() for item in merged}, {
            "Project Memory/a/Archive/Runs/shared.md", "Project Memory/a/Runs/shared.md"
        })

    def test_archive_destination_is_planned_for_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Demo")
            archive = vault / paths.archived_runs_dir
            archive.mkdir(parents=True)
            (archive / "shared.md").write_text("old", encoding="utf-8")
            run = RunMemory(Path("Project Memory/demo/Runs/shared.md"), "shared", "x", "2026", [], "", "", "", "", "", [])
            _plan_archive_destinations(vault, paths, [run])
            self.assertEqual(run.path, paths.archived_runs_dir / "shared-2.md")

    def test_qualified_related_link_preserves_dotted_note_name(self) -> None:
        self.assertIn(
            "[[Project Memory/demo/0.2.0 Home|0.2.0 Home]]",
            _related_entry("Project Memory/demo/0.2.0 Home", None),
        )

    def test_projects_index_append_separates_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            first = build_note_paths("Alpha")
            second = build_note_paths("Beta")
            ensure_projects_index(cli, first)
            ensure_projects_index(cli, second)
            body = (vault / "Project Memory" / "Projects Index.md").read_text(encoding="utf-8")
            self.assertIn(")\n- [[Project Memory/beta/Beta Home|Beta Home]]", body)

    def test_slugify(self) -> None:
        self.assertEqual(slugify("Sequency Project"), "sequency-project")
        self.assertEqual(slugify("  Mixed__Chars!! "), "mixed-chars")

    def test_parse_tags(self) -> None:
        self.assertEqual(parse_tags("swift,mxf, bugfix"), ["swift", "mxf", "bugfix"])
        self.assertEqual(parse_tags(""), [])

    def test_note_paths(self) -> None:
        paths = build_note_paths("Sequency")
        self.assertEqual(paths.project_slug, "sequency")
        self.assertEqual(paths.project_dir.as_posix(), "Project Memory/sequency")
        self.assertTrue(paths.home.as_posix().endswith("/Sequency Home.md"))

    def test_note_paths_sanitize_project_name(self) -> None:
        paths = build_note_paths("../../Secrets")
        self.assertTrue(paths.home.as_posix().startswith("Project Memory/secrets/"))
        self.assertNotIn("..", paths.home.as_posix())
        self.assertNotIn("/", paths.home.name.replace("Project Memory", ""))

    def test_sanitize_note_title_component(self) -> None:
        self.assertEqual(sanitize_note_title_component("../../evil"), "evil")
        self.assertEqual(sanitize_note_title_component("A/B\\\\C"), "A B C")
        self.assertEqual(sanitize_note_title_component(""), "Project")

    def test_seed_notes_include_interlinks(self) -> None:
        paths = build_note_paths("Sequency")
        notes = build_seed_notes("Sequency", paths)
        home = notes[paths.home]
        moc = notes[paths.moc]
        architecture = notes[paths.architecture]
        roadmap = notes[paths.roadmap]
        self.assertIn("[[Project Memory/sequency/MOC|MOC]]", home)
        self.assertIn("[[Project Memory/sequency/Sequency Home|Sequency Home]]", moc)
        self.assertIn("[[Project Memory/sequency/Architecture|Architecture]]", home)
        self.assertIn("[[Project Memory/sequency/Roadmap|Roadmap]]", home)
        self.assertIn("[[Project Memory/sequency/Current Memory|Current Memory]]", home)
        self.assertIn("[[Project Memory/sequency/Architecture|Architecture]]", moc)
        self.assertIn("[[Project Memory/sequency/Current Memory|Current Memory]]", moc)
        self.assertIn("[[Project Memory/sequency/MOC|MOC]]", architecture)
        self.assertIn("[[Project Memory/sequency/Debugging Notes|Debugging Notes]]", architecture)
        self.assertIn("[[Project Memory/sequency/Release Notes|Release Notes]]", roadmap)

    def test_seed_notes_create_topic_note_files(self) -> None:
        paths = build_note_paths("Sequency")
        notes = build_seed_notes("Sequency", paths)
        self.assertIn(paths.architecture, notes)
        self.assertIn(paths.roadmap, notes)
        self.assertIn(paths.debugging_notes, notes)
        self.assertIn(paths.release_notes, notes)
        self.assertIn(paths.current_memory, notes)
        self.assertEqual(len(notes), 10)

    def test_contains_cli_error(self) -> None:
        self.assertTrue(_contains_cli_error("Error: failed to open file"))
        self.assertTrue(_contains_cli_error("some info\nERROR cannot continue"))
        self.assertFalse(_contains_cli_error("Created: note.md"))

    def test_extract_wikilinks_preserves_dotted_note_names(self) -> None:
        links = _extract_wikilinks(
            "[[0.2.0 Home]] [[folder/release.1]] [[folder/Run.md|Run]]"
        )
        self.assertEqual(links, ["0.2.0 Home", "release.1", "Run"])

    def test_extract_wikilinks_ignores_markdown_code(self) -> None:
        body = "`[[Inline Example]]` [[Real Note]]\n```md\n[[Fenced Example]]\n```"
        self.assertEqual(_extract_wikilinks(body), ["Real Note"])

    def test_ensure_project_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Sequency")
            ensure_project_dirs(vault, paths, dry_run=False)
            self.assertTrue((vault / "Project Memory" / "sequency").is_dir())
            self.assertTrue((vault / "Project Memory" / "sequency" / "Runs").is_dir())

    def test_bootstrap_preserves_existing_home_filename_casing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            project_dir = vault / "Project Memory" / "basecamp"
            project_dir.mkdir(parents=True)
            canonical_home = project_dir / "Basecamp Home.md"
            canonical_home.write_text("# Basecamp Home\n", encoding="utf-8")

            paths = bootstrap_project(
                ObsidianCLI(vault_path=vault, dry_run=False),
                "basecamp",
            )

            self.assertEqual(paths.home.name, "Basecamp Home.md")
            self.assertIn(
                "[[Project Memory/basecamp/Basecamp Home|Basecamp Home]]",
                (project_dir / "Current Memory.md").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "basecamp Home.md",
                [item.name for item in project_dir.iterdir()],
            )

    def test_projects_index_path(self) -> None:
        self.assertEqual(PROJECTS_INDEX_PATH.as_posix(), "Project Memory/Projects Index.md")

    def test_list_projects_command_is_available(self) -> None:
        args = build_parser().parse_args(["list-projects"])
        self.assertEqual(args.command, "list-projects")

    def test_hook_scripts_run_directly_without_import_errors(self) -> None:
        skill_root = Path(__file__).resolve().parents[2]
        scripts = [
            "codex_notify_hook.py",
            "claude_notify_hook.py",
            "cursor_notify_hook.py",
            "antigravity_notify_hook.py",
        ]
        for script_name in scripts:
            with self.subTest(script=script_name):
                completed = subprocess.run(
                    [
                        "python3",
                        str(skill_root / "scripts" / script_name),
                        "--skill-repo",
                        str(skill_root),
                        "{",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotIn("ModuleNotFoundError", completed.stderr)

    def test_config_store_workspace_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_file = tmp_path / "vault_config.json"
            workspace = tmp_path / "workspace"
            nested = workspace / "nested" / "child"
            workspace.mkdir(parents=True, exist_ok=True)
            nested.mkdir(parents=True, exist_ok=True)
            vault = tmp_path / "vault"
            vault.mkdir(parents=True, exist_ok=True)

            store = ConfigStore(state_file=state_file)
            store.set_vault(vault_path=vault, workspace=workspace)
            resolved = store.resolve_vault(workspace=nested)
            self.assertEqual(resolved, str(vault.resolve()))

            raw = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(raw["default_vault_path"], str(vault.resolve()))

    def test_config_store_audit_frequency_and_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_file = tmp_path / "vault_config.json"
            workspace = tmp_path / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            store = ConfigStore(state_file=state_file)

            self.assertEqual(store.get_audit_every_runs(), DEFAULT_AUDIT_EVERY_RUNS)
            store.set_audit_every_runs(3)
            self.assertEqual(store.get_audit_every_runs(), 3)

            first = store.bump_run_counter(workspace, "sequency")
            second = store.bump_run_counter(workspace, "sequency")
            self.assertEqual(first, 1)
            self.assertEqual(second, 2)

            store.reset_run_counter(workspace, "sequency")
            reset = store.bump_run_counter(workspace, "sequency")
            self.assertEqual(reset, 1)

    def test_config_store_state_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_file = tmp_path / "vault_config.json"
            workspace = tmp_path / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            vault = tmp_path / "vault"
            vault.mkdir(parents=True, exist_ok=True)

            store = ConfigStore(state_file=state_file)
            store.set_vault(vault_path=vault, workspace=workspace)

            mode = state_file.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


    def test_build_or_query_single_word(self) -> None:
        self.assertEqual(_build_or_query("callback"), "callback")

    def test_build_or_query_multiple_words(self) -> None:
        result = _build_or_query("callback failure gizmo")
        self.assertEqual(result, "(callback OR failure OR gizmo)")

    def test_build_or_query_empty(self) -> None:
        self.assertEqual(_build_or_query(""), "")

    def test_search_priority_prefers_compacted_memory(self) -> None:
        self.assertGreater(
            _search_priority("Project Memory/demo/Current Memory.md"),
            _search_priority("Project Memory/demo/Runs/2026-01-01-foo.md"),
        )
        self.assertGreater(
            _search_priority("Project Memory/demo/Topics/Export.md"),
            _search_priority("Project Memory/demo/Archive/Runs/2026-01-01-foo.md"),
        )

    def test_search_skips_archive_unless_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            active = vault / "Project Memory" / "demo" / "Current Memory.md"
            archived = vault / "Project Memory" / "demo" / "Archive" / "Runs" / "old.md"
            active.parent.mkdir(parents=True, exist_ok=True)
            archived.parent.mkdir(parents=True, exist_ok=True)
            active.write_text("needle active\n", encoding="utf-8")
            archived.write_text("needle archived\n", encoding="utf-8")

            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            default_output = cli.search_files('needle path:"Project Memory/demo"')
            self.assertIn("Current Memory.md", default_output)
            self.assertNotIn("Archive/Runs/old.md", default_output)

            archive_output = cli.search_files(
                'needle path:"Project Memory/demo"',
                include_archive=True,
            )
            self.assertIn("Archive/Runs/old.md", archive_output)

    def _relevance_vault(self, tmp: str) -> Path:
        """A vault shaped like the failure: one huge hub note, one exact match."""
        vault = Path(tmp)
        project = vault / "Project Memory" / "demo"
        (project / "Topics").mkdir(parents=True, exist_ok=True)
        (project / "Runs").mkdir(parents=True, exist_ok=True)
        # A large topic note that never discusses the query, but whose ordinary
        # English contains "ai" inside words such as available and maintain.
        (project / "Topics" / "Audio.md").write_text(
            "Audio topic.\n" + ("available maintain detail chain certain " * 400),
            encoding="utf-8",
        )
        # A small note that is genuinely about the query.
        (project / "Runs" / "ollama-planner.md").write_text(
            "Integrate the local Ollama model planner for AI FX.\n"
            "The planner sends a schema to Ollama and validates the model plan.\n",
            encoding="utf-8",
        )
        return vault

    def test_search_ignores_substring_matches_inside_unrelated_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._relevance_vault(tmp)
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            output = cli.search_files('AI path:"Project Memory/demo"')
            # "available"/"maintain"/"chain" all contain "ai" as a substring.
            self.assertNotIn("Topics/Audio.md", output)
            self.assertIn("Runs/ollama-planner.md", output)

    def test_search_ranks_a_focused_note_above_a_large_incidental_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._relevance_vault(tmp)
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            output = cli.search_files(
                'AI FX local model planner Ollama path:"Project Memory/demo"'
            )
            listed = [line for line in output.splitlines() if line.startswith("  ")]
            self.assertTrue(listed, output)
            self.assertIn("Runs/ollama-planner.md", listed[0])

    def test_search_priority_boosts_ties_without_overriding_relevance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            project = vault / "Project Memory" / "demo"
            (project / "Runs").mkdir(parents=True, exist_ok=True)
            # A distilled note that barely mentions the query.
            (project / "Current Memory.md").write_text(
                "Current memory. The exporter writes frames.\nOllama is unrelated here.\n",
                encoding="utf-8",
            )
            # A run note that is squarely about it.
            (project / "Runs" / "ollama-planner.md").write_text(
                "Ollama planner. The Ollama planner validates each Ollama plan.\n"
                "Planner schema, planner fallback, planner worker.\n",
                encoding="utf-8",
            )
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            listed = [
                line
                for line in cli.search_files(
                    'Ollama planner path:"Project Memory/demo"'
                ).splitlines()
                if line.startswith("  ")
            ]
            self.assertIn("Runs/ollama-planner.md", listed[0])

            # With equal relevance the distilled note still wins.
            same = vault / "Project Memory" / "tie"
            (same / "Runs").mkdir(parents=True, exist_ok=True)
            body = "Ollama planner.\n"
            (same / "Current Memory.md").write_text(body, encoding="utf-8")
            (same / "Runs" / "a-run.md").write_text(body, encoding="utf-8")
            tied = [
                line
                for line in cli.search_files(
                    'Ollama planner path:"Project Memory/tie"'
                ).splitlines()
                if line.startswith("  ")
            ]
            self.assertIn("Current Memory.md", tied[0])

    def _run_memory(self, text: str, tags=None):
        from scripts.obsidian_memory import RunMemory, _keywords

        return RunMemory(
            path=Path("Project Memory/demo/Runs/x.md"),
            stem="x",
            title=text,
            created="2026-01-01T00:00:00+00:00",
            prompt="",
            summary=text,
            actions="",
            decisions="",
            questions="",
            tags=tags or [],
            keywords=_keywords(text, limit=12),
        )

    def test_topic_key_ignores_image_channels_as_audio(self) -> None:
        from scripts.obsidian_memory import _compact_topic_key

        # An image compositor mentions RGBA channels and pixel sampling
        # constantly; neither is evidence of audio work.
        run = self._run_memory(
            "Route RGBA channel selection through the viewer and sample "
            "each pixel channel with bilinear sampling."
        )
        self.assertNotEqual(_compact_topic_key(run, "demo"), "audio")

    def test_topic_key_still_recognises_real_audio_work(self) -> None:
        from scripts.obsidian_memory import _compact_topic_key

        run = self._run_memory(
            "Fix PCM audio export so the audio sample rate and audio channel "
            "layout survive the transcode."
        )
        self.assertEqual(_compact_topic_key(run, "demo"), "audio")

    def test_topic_key_prefers_the_dominant_subject_over_rule_order(self) -> None:
        from scripts.obsidian_memory import _compact_topic_key

        # "build" and "version" alone must not file a UI run under release
        # just because the release rule is declared earlier.
        run = self._run_memory(
            "Rebuild the inspector panel layout: the sidebar button, the panel "
            "scroll view and the panel selection now share one layout pass. "
            "Version 2 of the build."
        )
        self.assertEqual(_compact_topic_key(run, "demo"), "ui")

    def test_topic_key_ignores_the_agent_that_recorded_the_note(self) -> None:
        """How a note was captured is never what the note is about.

        Auto-logging hooks stamp "codex", "notify" and "hook" onto every note
        they write, which filed 170 of one project's 381 runs under tooling.
        """
        from scripts.obsidian_memory import _compact_topic_key

        run = self._run_memory(
            "Recorded by the codex notify hook during a claude turn. "
            "Fix the exr colour pipeline so acescg saturation survives.",
            tags=["codex", "exr"],
        )
        self.assertEqual(_compact_topic_key(run, "demo"), "color-management")

    def test_topic_key_still_files_genuine_tooling_work(self) -> None:
        from scripts.obsidian_memory import _compact_topic_key

        run = self._run_memory(
            "Add an mcp plugin and wire obsidian memory sync into the editor."
        )
        self.assertEqual(_compact_topic_key(run, "demo"), "tooling")

    def test_topic_key_uses_general_instead_of_arbitrary_keyword(self) -> None:
        from scripts.obsidian_memory import _compact_topic_key

        run = self._run_memory(
            "I need one thing under the current account before we continue."
        )
        self.assertEqual(_compact_topic_key(run, "demo"), "general")

    def test_distilled_sentences_drop_prompt_noise_and_redact_private_values(self) -> None:
        from scripts.obsidian_memory import _distilled_sentences

        text = " ".join(
            [
                "Do NOT respond to the user, answer questions, or attempt the task.",
                "<realtime_delegation><input>Use my private account</input></realtime_delegation>",
                "Verified the live display backend after the repair.",
                "Contact producer@example.com or +30 6912345678.",
                "Connected to 10.0.13.135 using the supplied key pair.",
                "Do not embed or print the API key.",
            ]
        )

        distilled = " ".join(_distilled_sentences(text))
        self.assertNotIn("Do NOT respond", distilled)
        self.assertNotIn("realtime_delegation", distilled)
        self.assertNotIn("producer@example.com", distilled)
        self.assertNotIn("6912345678", distilled)
        self.assertNotIn("10.0.13.135", distilled)
        self.assertNotIn("key pair", distilled)
        self.assertIn("Verified the live display backend", distilled)
        self.assertIn("[redacted email]", distilled)
        self.assertIn("[redacted phone]", distilled)
        self.assertIn("Do not embed or print the API key", distilled)

    def test_active_compaction_notes_never_repeat_private_or_prompt_content(self) -> None:
        from scripts.obsidian_memory import (
            _build_compaction_note,
            _build_current_memory_note,
            _build_topic_note,
        )

        run = self._run_memory("Export repair", tags=["export"])
        run.prompt = "Do NOT respond to the user or answer the request."
        run.summary = (
            "Verified export output. Contact producer@example.com or +30 6912345678."
        )
        run.actions = "Connected to 10.0.13.135 using the supplied key pair."
        run.decisions = "Keep the verified export operator path."
        paths = build_note_paths("Demo")
        topics = _build_topics(paths, [run])
        compaction_path = paths.compactions_dir / "2026-01-01-1000-compact-demo.md"
        active = "\n".join(
            [
                _build_current_memory_note("Demo", paths, compaction_path, topics, [run]),
                _build_compaction_note("Demo", paths, compaction_path, topics, [run]),
                _build_topic_note("Demo", paths, topics[0], topics),
            ]
        )

        for private_value in [
            "Do NOT respond",
            "producer@example.com",
            "6912345678",
            "10.0.13.135",
            "key pair",
        ]:
            self.assertNotIn(private_value, active)
        self.assertIn("Verified export output", active)
        self.assertIn("[redacted email]", active)
        self.assertIn("Keep the verified export operator path", active)

    def test_unlink_removes_both_sides_of_a_related_edge(self) -> None:
        """Auto-relate can weave a wrong edge; nothing could remove one.

        Removing a link by hand breaks the bidirectional invariant on one side,
        so the tool has to own the inverse of the operation it performs.
        """
        from scripts.obsidian_memory import remove_related_link, unweave_bidirectional

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            project = vault / "Project Memory" / "demo"
            project.mkdir(parents=True)
            run = project / "a-run.md"
            topic = project / "Audio.md"
            run.write_text(
                "# A run\n\n## Related\n\n- [[Audio]] — woven by mistake\n"
                "- [[Keep Me]] — still relevant\n",
                encoding="utf-8",
            )
            topic.write_text(
                "# Audio\n\n## Related\n\n- [[a-run]] — woven by mistake\n",
                encoding="utf-8",
            )

            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            statuses = unweave_bidirectional(
                cli,
                run.relative_to(vault),
                [topic.relative_to(vault)],
            )
            self.assertTrue(any("unlinked" in status for status in statuses), statuses)

            run_body = run.read_text(encoding="utf-8")
            topic_body = topic.read_text(encoding="utf-8")
            self.assertNotIn("[[Audio]]", run_body)
            self.assertNotIn("[[a-run]]", topic_body)
            # Unrelated edges and the section itself survive.
            self.assertIn("[[Keep Me]]", run_body)
            self.assertIn("## Related", run_body)

            # Removing an absent edge is a no-op, not an error.
            again = remove_related_link(cli, run.relative_to(vault), "Audio")
            self.assertIn("absent", again)

    def test_unlink_notes_command_is_available(self) -> None:
        args = build_parser().parse_args(
            ["unlink-notes", "--project", "demo", "--from", "a", "--to", "b"]
        )
        self.assertEqual(args.command, "unlink-notes")

    def test_audit_scope_excludes_unrelated_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            demo = vault / "Project Memory" / "demo"
            other = vault / "Project Memory" / "other"
            demo.mkdir(parents=True)
            other.mkdir(parents=True)
            (demo / "linked.md").write_text("[[Missing Demo]]\n", encoding="utf-8")
            (demo / "dead.md").write_text("No links here.\n", encoding="utf-8")
            archived = demo / "Archive" / "Runs" / "old.md"
            archived.parent.mkdir(parents=True)
            archived.write_text("Cold evidence with no backlinks.\n", encoding="utf-8")
            (other / "other.md").write_text("[[Missing Other]]\n", encoding="utf-8")
            (other / "dead-other.md").write_text("No links here.\n", encoding="utf-8")

            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            scope = Path("Project Memory/demo")

            unresolved = cli.audit_unresolved(verbose=True, scope=scope)
            self.assertIn("Missing Demo", unresolved)
            self.assertNotIn("Missing Other", unresolved)

            orphans = cli.audit_orphans(scope=scope)
            self.assertIn("Project Memory/demo/dead.md", orphans)
            self.assertNotIn("Archive/Runs/old.md", orphans)
            self.assertNotIn("Project Memory/other", orphans)

            deadends = cli.audit_deadends(scope=scope)
            self.assertIn("Project Memory/demo/dead.md", deadends)
            self.assertNotIn("dead-other.md", deadends)

    def test_audit_scope_cannot_escape_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli = ObsidianCLI(vault_path=Path(tmp), dry_run=False)
            with self.assertRaisesRegex(RuntimeError, "Audit scope escapes vault"):
                cli.audit_deadends(scope=Path("../outside"))


class BidirectionalLinkTests(unittest.TestCase):
    def test_parse_related_arg_handles_commas_and_newlines(self) -> None:
        self.assertEqual(_parse_related_arg("a, b,\nc"), ["a", "b", "c"])
        self.assertEqual(_parse_related_arg(""), [])
        self.assertEqual(_parse_related_arg(None), [])

    def test_has_link_to(self) -> None:
        body = "Some text [[alpha]] and [[beta|display]] done."
        self.assertTrue(_has_link_to(body, "alpha"))
        self.assertTrue(_has_link_to(body, "beta"))
        self.assertFalse(_has_link_to(body, "gamma"))
        # Partial names must not match.
        self.assertFalse(_has_link_to(body, "alph"))

    def test_append_to_related_section_creates_section(self) -> None:
        body = "# Note\n\nBody text.\n"
        result = _append_to_related_section(body, "- [[neighbor]] — reason")
        self.assertIn("## Related", result)
        self.assertIn("- [[neighbor]] — reason", result)
        # Section must not appear twice.
        self.assertEqual(result.count("## Related"), 1)

    def test_append_to_related_section_extends_existing(self) -> None:
        body = (
            "# Note\n\n"
            "Body.\n\n"
            "## Related\n\n"
            "- [[first]]\n\n"
            "## Later Heading\n\n"
            "More text.\n"
        )
        result = _append_to_related_section(body, "- [[second]]")
        self.assertEqual(result.count("## Related"), 1)
        # New entry must come after existing entry but before the next heading.
        related_idx = result.index("## Related")
        later_idx = result.index("## Later Heading")
        second_idx = result.index("- [[second]]")
        first_idx = result.index("- [[first]]")
        self.assertLess(related_idx, first_idx)
        self.assertLess(first_idx, second_idx)
        self.assertLess(second_idx, later_idx)

    def test_resolve_note_path_by_stem_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("TestProj")
            runs_dir = vault / paths.runs_dir
            runs_dir.mkdir(parents=True, exist_ok=True)
            note = runs_dir / "2026-04-11-1530-foo.md"
            note.write_text("# Foo\n", encoding="utf-8")

            # Resolve by stem.
            resolved = resolve_note_path(vault, paths, "2026-04-11-1530-foo")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved, note.relative_to(vault))

            # Resolve by wikilink form.
            resolved_wiki = resolve_note_path(vault, paths, "[[2026-04-11-1530-foo]]")
            self.assertEqual(resolved_wiki, note.relative_to(vault))

            # Resolve by full relative path.
            resolved_full = resolve_note_path(
                vault, paths, note.relative_to(vault).as_posix()
            )
            self.assertEqual(resolved_full, note.relative_to(vault))

            # Missing → None.
            self.assertIsNone(resolve_note_path(vault, paths, "ghost-note"))

    def test_ensure_related_link_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("TestProj")
            runs_dir = vault / paths.runs_dir
            runs_dir.mkdir(parents=True, exist_ok=True)
            target = runs_dir / "target.md"
            target.write_text("# Target\n\nBody.\n", encoding="utf-8")

            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            rel = target.relative_to(vault)

            first = ensure_related_link(cli, rel, "neighbor", reason="because")
            self.assertTrue(first.startswith("linked:"))
            body1 = target.read_text(encoding="utf-8")
            self.assertIn("## Related", body1)
            self.assertIn("- [[neighbor]] — because", body1)

            # Second call with same target must be a no-op.
            second = ensure_related_link(cli, rel, "neighbor", reason="because")
            self.assertTrue(second.startswith("skipped:"))
            self.assertEqual(target.read_text(encoding="utf-8"), body1)

            # Self-link must be rejected.
            self_result = ensure_related_link(cli, rel, "target", reason=None)
            self.assertTrue(self_result.startswith("self:"))

    def test_weave_bidirectional_creates_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("TestProj")
            runs_dir = vault / paths.runs_dir
            runs_dir.mkdir(parents=True, exist_ok=True)
            a = runs_dir / "note-a.md"
            b = runs_dir / "note-b.md"
            a.write_text("# A\n", encoding="utf-8")
            b.write_text("# B\n", encoding="utf-8")

            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            results = weave_bidirectional(
                cli,
                a.relative_to(vault),
                [b.relative_to(vault)],
                reason="test edge",
            )
            # Two status lines per neighbor (forward + reverse).
            self.assertEqual(len(results), 2)
            body_a = a.read_text(encoding="utf-8")
            body_b = b.read_text(encoding="utf-8")
            self.assertIn("[[Project Memory/testproj/Runs/note-b|note-b]]", body_a)
            self.assertIn("[[Project Memory/testproj/Runs/note-a|note-a]]", body_b)

    def test_parse_search_output_paths(self) -> None:
        output = (
            "Found 3 hits:\n"
            "  Project Memory/sequency/Runs/2026-04-11-a.md (score 12)\n"
            '  "Project Memory/sequency/Runs/2026-04-11-b.md"\n'
            "  unrelated.txt\n"
            "  Project Memory/sequency/Runs/2026-04-11-a.md  (duplicate)\n"
        )
        result = _parse_search_output_paths(output)
        self.assertEqual(
            result,
            [
                "Project Memory/sequency/Runs/2026-04-11-a.md",
                "Project Memory/sequency/Runs/2026-04-11-b.md",
            ],
        )


class CompactionTests(unittest.TestCase):
    def test_collect_and_group_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Demo")
            runs_dir = vault / paths.runs_dir
            runs_dir.mkdir(parents=True, exist_ok=True)
            (runs_dir / "2026-01-01-1000-export-fix.md").write_text(
                "\n".join(
                    [
                        "---",
                        'type: "run"',
                        'project: "Demo"',
                        "tags:",
                        '  - "export"',
                        '  - "run"',
                        'title: "Export fix"',
                        "---",
                        "",
                        "# Export fix",
                        "",
                        "## Prompt",
                        "Fix export failure.",
                        "",
                        "## Summary",
                        "Fixed export routing and verified output pixels.",
                        "",
                        "## Actions Taken",
                        "Updated exporter path.",
                        "",
                        "## Decisions",
                        "Prefer real output verification.",
                        "",
                        "## Open Questions",
                        "None.",
                    ]
                ),
                encoding="utf-8",
            )

            runs = _collect_uncompacted_runs(vault, paths, limit=None)
            self.assertEqual(len(runs), 1)
            topics = _build_topics(paths, runs)
            self.assertEqual(len(topics), 1)
            self.assertEqual(topics[0].key, "export")

    def test_compact_project_archives_runs_and_writes_hot_memory(self) -> None:
        original_state_env = os.environ.get("OBMEM_STATE_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                vault = root / "vault"
                workspace = root / "workspace"
                os.environ["OBMEM_STATE_FILE"] = str(root / "state" / "vault_config.json")
                vault.mkdir(parents=True)
                workspace.mkdir(parents=True)
                ConfigStore().set_vault(vault_path=vault, workspace=workspace)
                paths = build_note_paths("Demo")
                runs_dir = vault / paths.runs_dir
                runs_dir.mkdir(parents=True, exist_ok=True)
                for idx, topic in enumerate(["export", "export", "permissions"], start=1):
                    stem = f"2026-01-01-100{idx}-{topic}-run"
                    (runs_dir / f"{stem}.md").write_text(
                        "\n".join(
                            [
                                "---",
                                'type: "run"',
                                'project: "Demo"',
                                "tags:",
                                f'  - "{topic}"',
                                '  - "run"',
                                f'title: "{topic} run"',
                                "---",
                                "",
                                f"# {topic} run",
                                "",
                                "Parent note: [[Demo Home]]",
                                "MOC: [[MOC]]",
                                "Run log: [[Run Log]]",
                                "",
                                "## Prompt",
                                f"Fix {topic} bug.",
                                "",
                                "## Summary",
                                f"Fixed {topic} behavior and verified the real output path.",
                                "",
                                "## Actions Taken",
                                f"Changed the {topic} implementation.",
                                "",
                                "## Decisions",
                                "Prefer concrete proof before reporting success.",
                                "",
                                "## Open Questions",
                                "None.",
                                "",
                                "## Related",
                                "",
                                "- [[old-noisy-neighbor]]",
                            ]
                        ),
                        encoding="utf-8",
                    )
                (vault / paths.run_log).parent.mkdir(parents=True, exist_ok=True)
                (vault / paths.run_log).write_text(
                    "# Run Log\n\n## Entries\n"
                    "- [[2026-01-01-1001-export-run]]: noisy\n"
                    "- [[2026-01-01-1002-export-run]]: noisy\n",
                    encoding="utf-8",
                )
                runs_rel = paths.runs_dir.as_posix()
                (vault / paths.decisions).write_text(
                    "# Decisions\n\n## Decision Register\n"
                    f"- [[{runs_rel}/2026-01-01-1001-export-run|2026-01-01-1001-export-run]]: Export writes atomically.\n",
                    encoding="utf-8",
                )
                (vault / paths.questions).write_text(
                    "# Open Questions\n\n## Question Log\n"
                    "- [[2026-01-01-1003-permissions-run]]: Should permissions be cached?\n",
                    encoding="utf-8",
                )

                args = argparse.Namespace(
                    project="Demo",
                    max_runs=0,
                    no_archive=False,
                    include_archive=False,
                    workspace=str(workspace),
                    dry_run=False,
                )
                cmd_compact_project(args)

                self.assertEqual(list(runs_dir.glob("*.md")), [])
                archived = sorted((vault / paths.archived_runs_dir).glob("*.md"))
                self.assertEqual(len(archived), 3)
                self.assertTrue((vault / paths.current_memory).exists())
                self.assertTrue((vault / paths.topics_dir / "Export.md").exists())
                self.assertTrue((vault / paths.compactions_dir).is_dir())

                archived_body = archived[0].read_text(encoding="utf-8")
                self.assertIn('status: "compacted"', archived_body)
                self.assertIn("## Archived Source", archived_body)
                self.assertNotIn("[[old-noisy-neighbor]]", archived_body)
                run_log = (vault / paths.run_log).read_text(encoding="utf-8")
                self.assertNotIn("[[2026-01-01-1001-export-run]]: noisy", run_log)
                self.assertIn("Compacted 3 run note(s)", run_log)

                # Registers keep every entry; the link follows the run into the archive.
                archive_rel = paths.archived_runs_dir.as_posix()
                decisions = (vault / paths.decisions).read_text(encoding="utf-8")
                self.assertIn(
                    f"- [[{archive_rel}/2026-01-01-1001-export-run|2026-01-01-1001-export-run]]: Export writes atomically.",
                    decisions,
                )
                questions = (vault / paths.questions).read_text(encoding="utf-8")
                self.assertIn(f"[[{archive_rel}/2026-01-01-1003-permissions-run|2026-01-01-1003-permissions-run]]: Should permissions be cached?", questions)

                # A second compaction does not repeat the retrieval rule.
                (runs_dir / "2026-01-02-1001-export-run.md").write_text(
                    '---\ntype: "run"\nproject: "Demo"\ntags:\n  - "export"\ntitle: "export follow-up"\n---\n\n'
                    "# export follow-up\n\n## Summary\nVerified the export path again.\n",
                    encoding="utf-8",
                )
                cmd_compact_project(args)
                self.assertEqual(list(runs_dir.glob("*.md")), [])
                decisions = (vault / paths.decisions).read_text(encoding="utf-8")
                self.assertEqual(decisions.count("topic notes before raw archived run notes for retrieval."), 1)
                self.assertIn("Export writes atomically.", decisions)
        finally:
            if original_state_env is None:
                os.environ.pop("OBMEM_STATE_FILE", None)
            else:
                os.environ["OBMEM_STATE_FILE"] = original_state_env

    def test_bounded_compactions_preserve_prior_distilled_memory(self) -> None:
        original_state_env = os.environ.get("OBMEM_STATE_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                vault = root / "vault"
                workspace = root / "workspace"
                os.environ["OBMEM_STATE_FILE"] = str(root / "state" / "vault_config.json")
                vault.mkdir(parents=True)
                workspace.mkdir(parents=True)
                ConfigStore().set_vault(vault_path=vault, workspace=workspace)
                paths = build_note_paths("Demo")
                runs_dir = vault / paths.runs_dir
                runs_dir.mkdir(parents=True, exist_ok=True)

                for idx, (tag, summary) in enumerate(
                    [
                        ("export", "Fixed export routing and verified output pixels."),
                        ("permissions", "Fixed sandbox permissions and verified access."),
                    ],
                    start=1,
                ):
                    (runs_dir / f"2026-01-01-100{idx}-{tag}.md").write_text(
                        "\n".join(
                            [
                                "---",
                                'type: "run"',
                                'project: "Demo"',
                                "tags:",
                                f'  - "{tag}"',
                                '  - "run"',
                                f'title: "{tag} run"',
                                "---",
                                "",
                                f"# {tag} run",
                                "",
                                "## Prompt",
                                f"Fix {tag} behavior.",
                                "",
                                "## Summary",
                                summary,
                                "",
                                "## Actions Taken",
                                f"Changed the {tag} implementation.",
                                "",
                                "## Decisions",
                                f"Preserve the {tag} operator path.",
                                "",
                                "## Open Questions",
                                "None.",
                            ]
                        ),
                        encoding="utf-8",
                    )

                args = argparse.Namespace(
                    project="Demo",
                    max_runs=1,
                    no_archive=False,
                    include_archive=False,
                    workspace=str(workspace),
                    dry_run=False,
                )
                cmd_compact_project(args)
                cmd_compact_project(args)

                current = (vault / paths.current_memory).read_text(encoding="utf-8")
                self.assertIn("[[Project Memory/demo/Topics/Export|Export]]", current)
                self.assertIn("[[Project Memory/demo/Topics/Permissions|Permissions]]", current)
                self.assertTrue((vault / paths.topics_dir / "Export.md").exists())
                self.assertTrue((vault / paths.topics_dir / "Permissions.md").exists())
                self.assertEqual(len(list((vault / paths.archived_runs_dir).glob("*.md"))), 2)
                self.assertEqual(len(list((vault / paths.compactions_dir).glob("*.md"))), 2)
        finally:
            if original_state_env is None:
                os.environ.pop("OBMEM_STATE_FILE", None)
            else:
                os.environ["OBMEM_STATE_FILE"] = original_state_env


class SearchExcludesSessionTests(unittest.TestCase):
    def test_own_notes_are_left_out_before_the_limit(self) -> None:
        from scripts.obsidian_memory import ObsidianCLI
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "Project Memory" / "demo" / "Runs"
            runs.mkdir(parents=True)
            for i in range(10):
                (runs / f"own-{i}.md").write_text(
                    f'---\nsession: "s-1"\ncreated: "2026-11-10T12:00:00+00:00"\n---\n# kafka lag {i}\n')
            (runs / "earlier.md").write_text('---\nsession: "s-0"\n---\n# kafka lag earlier\n')
            cli = ObsidianCLI(vault_path=Path(tmp), dry_run=False)
            with patch.dict(os.environ, {"OBMEM_EXCLUDE_SESSION": "s-1", "OBMEM_EXCLUDE_SINCE": "0"}):
                hits = cli.search_files('kafka path:"Project Memory/demo"', limit=10)
            self.assertIn("earlier.md", hits)
            self.assertNotIn("own-", hits)
            # After a compaction at 13:00, the 12:00 notes count again.
            since = "1794315600"  # 2026-11-10T13:00:00Z
            with patch.dict(os.environ, {"OBMEM_EXCLUDE_SESSION": "s-1", "OBMEM_EXCLUDE_SINCE": since}):
                self.assertIn("own-", cli.search_files('kafka path:"Project Memory/demo"', limit=20))


class WriteSummaryOnceTests(unittest.TestCase):
    def test_brief_takes_the_first_sentence_and_cuts_on_a_word(self) -> None:
        from scripts.obsidian_memory import _brief
        self.assertEqual(_brief("Fixed the lag.  Raised fetch size to 4 MB.", 160), "Fixed the lag.")
        self.assertEqual(_brief("v1.5 shipped to testers", 160), "v1.5 shipped to testers")
        long = "word " * 60
        cut = _brief(long, 40)
        self.assertLessEqual(len(cut), 40)
        self.assertTrue(cut.endswith("..."))
        self.assertEqual(_brief("", 40), "")

    def test_related_entry_keeps_an_explicit_reason_whole(self) -> None:
        from scripts.obsidian_memory import _related_entry
        reason = "Supersedes X. Do not use the old flow."
        self.assertEqual(_related_entry("note-a", reason), f"- [[note-a]] — {reason}")
        self.assertEqual(_related_entry("note-a", "a\nb"), "- [[note-a]] — a b")
        self.assertEqual(_related_entry("note-a", None), "- [[note-a]]")

    def test_brief_never_leaves_half_a_link_or_code_span(self) -> None:
        from scripts.obsidian_memory import _brief, _extract_wikilinks
        text = "Moved the export flow and the cache reader " * 3 + "see [[Decision Register|the notes]] here"
        for limit in range(60, 200, 7):
            out = _brief(text, limit)
            self.assertEqual(out.count("[["), out.count("]]"), out)
        self.assertEqual(_brief("Run `git log --oneline` then rebase", 12).count("`") % 2, 0)
        lines = "- [[a]]: " + _brief(text, 150) + "\n- [[b]]: next"
        self.assertIn("b", _extract_wikilinks(lines))

    def test_brief_does_not_stop_at_abbreviations(self) -> None:
        from scripts.obsidian_memory import _brief
        self.assertEqual(_brief("Use e.g. Redis for the cache. Then more.", 160), "Use e.g. Redis for the cache.")
        self.assertEqual(_brief("- fixed X\n- fixed Y", 160), "fixed X - fixed Y")

    def test_empty_values_mean_no_section(self) -> None:
        from scripts.obsidian_memory import _has_content
        for value in (None, "", " ", "None", "None.", "none", "N/A", "-"):
            self.assertFalse(_has_content(value))
        self.assertTrue(_has_content("Prefer measured counts."))


class RelatedNeighborTests(unittest.TestCase):
    def test_auto_notes_and_full_notes_are_not_linked_automatically(self) -> None:
        from scripts.obsidian_memory import _good_neighbor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = root / "manual.md"
            manual.write_text('---\ntags:\n  - "export"\n  - "run"\n---\n# Fix export\n')
            auto = root / "auto.md"
            auto.write_text('---\ntags:\n  - "claude"\n  - "auto-log"\n---\n# Message from X\n')
            full = root / "full.md"
            full.write_text("# Busy\n\n## Related\n" + "".join(f"- [[n{i}]]\n" for i in range(12)))
            body_mention = root / "mention.md"
            body_mention.write_text('---\ntags:\n  - "run"\n---\nWe stopped tagging notes\n  - auto-log\n')
            self.assertTrue(_good_neighbor(manual))
            self.assertFalse(_good_neighbor(auto))
            self.assertFalse(_good_neighbor(full))
            self.assertTrue(_good_neighbor(body_mention))
            self.assertFalse(_good_neighbor(root / "missing.md"))
            mirror = root / "mirror.md"
            mirror.write_text('---\ntags:\n  - "auto-log"\n  - "memory-sync"\n---\n# Memory sync\n')
            self.assertTrue(_good_neighbor(mirror))
            inline = root / "inline.md"
            inline.write_text("---\ntags: [claude, 'auto-log']\n---\n# x\n")
            self.assertFalse(_good_neighbor(inline))


class RelatedDescriptionTests(unittest.TestCase):
    def test_compaction_reports_are_not_linked_automatically(self) -> None:
        from unittest import mock
        from scripts.obsidian_memory import auto_discover_neighbors
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "Compactions"  # a vault folder with that name must not matter
            paths = build_note_paths("P")
            report = paths.project_dir / "Compactions" / "2026-11-11-compact-p.md"
            run = paths.runs_dir / "2026-11-11-fix.md"
            for rel in (report, run):
                (vault / rel).parent.mkdir(parents=True, exist_ok=True)
                (vault / rel).write_text("# Note\n\n## Summary\nFix.\n")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            out = f"{report.as_posix()}\n{run.as_posix()}\n"
            with mock.patch.object(cli, "run", return_value=out):
                self.assertEqual(auto_discover_neighbors(cli, paths, "fix", 5), [run])

    def test_each_side_of_an_edge_describes_the_note_it_points_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            runs = vault / build_note_paths("TestProj").runs_dir
            runs.mkdir(parents=True)
            new = runs / "new.md"
            old = runs / "old.md"
            topic = runs / "topic.md"
            new.write_text("# New\n\n## Summary\nAdded the cache.\n")
            old.write_text("# Old\n\n## Summary\nFixed export\nlag. More detail.\n")
            topic.write_text("# Topic\n\n## Key Takeaways\n- Exports use measured counts.\n- Other.\n")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            weave_bidirectional(
                cli, new.relative_to(vault),
                [old.relative_to(vault), topic.relative_to(vault)],
                "Added the cache.", describe_neighbors=True,
            )
            body_new = new.read_text()
            self.assertIn("|old]] — Fixed export lag.\n", body_new)
            self.assertIn("|topic]] — Exports use measured counts.\n", body_new)
            self.assertNotIn("— Added the cache.", body_new)
            self.assertIn("|new]] — Added the cache.", old.read_text())
            self.assertIn("|new]] — Added the cache.", topic.read_text())


class NewestFirstTests(unittest.TestCase):
    def test_capped_topic_lists_start_from_the_newest_run(self) -> None:
        from scripts.obsidian_memory import (
            RunMemory, TopicMemory, _build_topic_note, _build_current_memory_note, COMPACTION_NOTE_LIMIT,
        )
        paths = build_note_paths("Demo")
        runs = [
            RunMemory(path=paths.runs_dir / f"r{i:02d}.md", stem=f"r{i:02d}", title=f"Run {i}",
                      created=f"2026-11-{i + 1:02d}T10:00:00", tags=["git"], prompt="p",
                      summary=f"Change number {i} landed on main.", actions=f"Ran suite {i}.",
                      decisions=f"Keep rule {i} for good.", questions="", keywords=["git"])
            for i in range(COMPACTION_NOTE_LIMIT + 6)
        ]
        newest = runs[-1]
        topic = TopicMemory(key="git", title="GIT", path=paths.topics_dir / "GIT.md",
                            runs=list(runs), keywords=["git"], related=[])
        note = _build_topic_note("Demo", paths, topic, [topic])
        takeaways = note.split("## Key Takeaways\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(takeaways.startswith(f"- {newest.summary}"), takeaways[:80])
        self.assertNotIn(runs[0].summary, takeaways)  # oldest falls past the cap
        from unittest import mock
        with mock.patch("scripts.obsidian_memory.COMPACTION_SOURCE_LIMIT", 3):
            sources = _build_topic_note("Demo", paths, topic, [topic]).split("## Source Runs", 1)[1]
        self.assertIn(newest.stem, sources)
        self.assertNotIn(runs[0].stem + "|", sources)
        current = _build_current_memory_note("Demo", paths, paths.compactions_dir / "c.md", [topic], runs)
        self.assertIn(f"— {newest.summary}", current)
        self.assertIn(f"- {newest.decisions}", current)


class TopicSentenceTests(unittest.TestCase):
    def test_fragments_are_not_kept_as_takeaways(self) -> None:
        from scripts.obsidian_memory import _distilled_sentences
        text = ("Honest answer up front: macOS has no per-app bandwidth API. "
                "`★ Insight ─────` Fixed the export path; it now writes atomically. "
                "**Could you either:** 1. Tatiana's draft was left...\n"
                "- Use e.g. Redis for the cache.\n- and then it broke")
        got = _distilled_sentences(text)
        self.assertIn("macOS has no per-app bandwidth API.", got)
        self.assertIn("Fixed the export path; it now writes atomically.", got)
        self.assertIn("Use e.g. Redis for the cache.", got)
        for bad in ("Could you either", "Tatiana", "and then it broke", "Insight", "Honest answer"):
            self.assertFalse(any(bad in sentence for sentence in got), bad)

    def test_review_cases_keep_meaning_and_short_decisions(self) -> None:
        from scripts.obsidian_memory import _distilled_sentences as d
        self.assertEqual(d("No migration is required."), ["No migration is required."])
        self.assertEqual(d("Use Postgres."), ["Use Postgres."])
        self.assertEqual(d("We target Python 3."), ["We target Python 3."])
        self.assertEqual(d("to-do list is broken in obmem"), ["to-do list is broken in obmem"])
        self.assertEqual(d("we decided to use\nPostgres because it is faster."),
                         ["we decided to use Postgres because it is faster."])
        self.assertEqual(len(d("Πρώτη πρόταση εδώ. Δεύτερη πρόταση εκεί.")), 2)
        self.assertEqual(d("Keep src/**/*.ts in the build."), ["Keep src/**/*.ts in the build."])
        self.assertEqual(d("Fixed one; it now writes atomically."), ["Fixed one; it now writes atomically."])

    def test_secret_on_the_next_line_is_not_kept(self) -> None:
        from scripts.obsidian_memory import _distilled_sentences as d
        got = d("Password:\nCorrect Horse Battery Staple\n\nThe deploy worked fine today.")
        self.assertFalse(any("Horse" in sentence for sentence in got), got)
        self.assertIn("The deploy worked fine today.", got)


class RelatedHeadingTests(unittest.TestCase):
    def test_related_topics_section_is_not_the_related_section(self) -> None:
        topic = "# Tooling\n\n## Related Topics\n- [[Testing]]\n\n## Source Runs\n- [[run-a]]\n"
        out = _append_to_related_section(topic, "- [[run-b]] — why")
        self.assertIn("## Related Topics\n- [[Testing]]\n\n## Source Runs", out)
        self.assertTrue(out.rstrip().endswith("## Related\n\n- [[run-b]] — why"))

    def test_existing_related_section_after_related_topics_is_used(self) -> None:
        note = "# T\n\n## Related Topics\n- [[X]]\n\n## Related\n\n- [[a]]\n"
        out = _append_to_related_section(note, "- [[b]]")
        self.assertEqual(out.count("## Related\n"), 1)
        self.assertIn("- [[a]]\n- [[b]]", out)
        self.assertIn("## Related Topics\n- [[X]]\n", out)


class CompactionKeepsLinksTests(unittest.TestCase):
    def test_compaction_leaves_no_new_broken_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Demo")
            other = vault / "Project Memory" / "other"
            for directory in (paths.runs_dir, paths.archived_runs_dir, paths.topics_dir, paths.compactions_dir):
                (vault / directory).mkdir(parents=True)
            other.mkdir(parents=True)
            run = '---\ntype: "run"\nproject: "Demo"\ntags:\n  - "export"\n---\n\n# {t}\n\n## Summary\n{s}\n'
            (vault / paths.runs_dir / "2026-11-01-1000-fix-export.md").write_text(
                run.format(t="Fix export", s="Export now writes atomically to the output folder."))
            (vault / paths.runs_dir / "2026-11-02-1000-cache-reader.md").write_text(
                run.format(t="Cache reader", s="The cache reader keeps file handles closed after reads."))
            (vault / paths.topics_dir / "Video Export.md").write_text("# Video Export\n\nOld topic.\n")
            runs = paths.runs_dir.as_posix()
            topics = paths.topics_dir.as_posix()
            (vault / paths.compactions_dir / "2026-10-01-0900-compact-demo.md").write_text(
                "# Older compaction\n\n## Topics\n"
                f"- [[{topics}/Video Export|Video Export]]\n\n## Related\n"
                f"- [[{runs}/2026-11-01-1000-fix-export|2026-11-01-1000-fix-export]] — why\n"
                f"- [[{runs}/2026-11-02-1000-cache-reader#Summary]]\n")
            (other / "note.md").write_text(f"See [[{runs}/2026-11-01-1000-fix-export.md]].\n")
            cli = ObsidianCLI(vault, False)
            self.assertIn("0 unresolved link target", cli.audit_unresolved(verbose=True))
            args = build_parser().parse_args(["compact-project", "--project", "Demo"])
            with patch("scripts.obsidian_memory.resolve_vault_or_exit", return_value=vault), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                cmd_compact_project(args)
            self.assertFalse(any((vault / paths.runs_dir).glob("*.md")), "runs were archived")
            self.assertFalse((vault / paths.topics_dir / "Video Export.md").exists(), "stale topic retired")
            self.assertIn("0 unresolved link target", cli.audit_unresolved(verbose=True))
            self.assertIn("Other links moved to archived runs and topics: 4", out.getvalue())


class RepointMovedLinksTests(unittest.TestCase):
    def test_path_links_follow_runs_into_the_archive(self) -> None:
        from scripts.obsidian_memory import _repoint_moved_links
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            pm = vault / "Project Memory"
            (pm / "demo" / "Archive" / "Runs").mkdir(parents=True)
            (pm / "demo" / "Compactions").mkdir(parents=True)
            (pm / "other").mkdir(parents=True)
            src = Path("Project Memory/demo/Runs/2026-11-01-1000-fix-export.md")
            dest = Path("Project Memory/demo/Archive/Runs/2026-11-01-1000-fix-export.md")
            (vault / dest).write_text("# Fix export\n")
            old = (pm / "demo" / "Compactions" / "old.md")
            old.write_text(
                "## Related\n"
                "- [[Project Memory/demo/Runs/2026-11-01-1000-fix-export|2026-11-01-1000-fix-export]] — why\n"
                "- [[Project Memory/demo/Runs/2026-11-01-1000-fix-export#Summary]]\n"
                "- [[2026-11-01-1000-fix-export]]\n"
                "- [[Project Memory/demo/Runs/2026-11-01-1000-other|other]]\n")
            cross = pm / "other" / "note.md"
            cross.write_text("See [[Project Memory/demo/Runs/2026-11-01-1000-fix-export]].\n")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            self.assertEqual(_repoint_moved_links(cli, [(src, dest)]), (3, 2))
            body = old.read_text()
            self.assertIn("[[Project Memory/demo/Archive/Runs/2026-11-01-1000-fix-export|2026-11-01-1000-fix-export]] — why", body)
            self.assertIn("[[Project Memory/demo/Archive/Runs/2026-11-01-1000-fix-export#Summary]]", body)
            self.assertIn("- [[2026-11-01-1000-fix-export]]", body)
            self.assertIn("[[Project Memory/demo/Runs/2026-11-01-1000-other|other]]", body)
            self.assertIn("[[Project Memory/demo/Archive/Runs/2026-11-01-1000-fix-export]]", cross.read_text())
            self.assertEqual(_repoint_moved_links(cli, []), (0, 0))

    def test_other_link_forms_embeds_and_code(self) -> None:
        from scripts.obsidian_memory import _repoint_moved_links
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            note = vault / "Project Memory" / "demo" / "n.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "[[Project Memory/demo/Runs/x.md]] [[project memory/demo/runs/X]]\n"
                "| [[Project Memory/demo/Runs/x\\|alias]] |\n"
                "![[Project Memory/demo/Runs/x]] `[[Project Memory/demo/Runs/x]]`\n")
            src, dest = Path("Project Memory/demo/Runs/x.md"), Path("Project Memory/demo/Archive/Runs/x.md")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            self.assertEqual(_repoint_moved_links(cli, [(src, dest)]), (3, 1))
            body = note.read_text()
            self.assertEqual(body.count("[[Project Memory/demo/Archive/Runs/x"), 3)
            self.assertIn("[[Project Memory/demo/Archive/Runs/x\\|alias]]", body)
            self.assertIn("![[Project Memory/demo/Runs/x]]", body)
            self.assertIn("`[[Project Memory/demo/Runs/x]]`", body)

    def test_links_inside_a_nested_fence_stay(self) -> None:
        from scripts.obsidian_memory import _repoint_moved_links
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            note = vault / "Project Memory" / "demo" / "doc.md"
            note.parent.mkdir(parents=True)
            body = ("````markdown\n```\nexample\n```\n[[Project Memory/demo/Runs/x]]\n````\n"
                    "Real: [[Project Memory/demo/Runs/x]]\n")
            note.write_text(body)
            moved = [(Path("Project Memory/demo/Runs/x.md"), Path("Project Memory/demo/Archive/Runs/x.md"))]
            self.assertEqual(_repoint_moved_links(ObsidianCLI(vault_path=vault, dry_run=False), moved), (1, 1))
            text = note.read_text()
            self.assertIn("```\n[[Project Memory/demo/Runs/x]]\n````", text)
            self.assertIn("Real: [[Project Memory/demo/Archive/Runs/x]]", text)

    def test_append_during_a_rewrite_is_not_lost(self) -> None:
        import threading
        from scripts.obsidian_memory import _rewrite_note, fcntl as lock_module
        if lock_module is None:
            self.skipTest("no advisory locks on this platform")
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            note = vault / "n.md"
            note.write_text("see [[old]]\n")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            holder = note.open("a+b")
            lock_module.flock(holder.fileno(), lock_module.LOCK_EX)  # an appender is mid-write
            worker = threading.Thread(target=_rewrite_note,
                                      args=(note, lambda t: (t.replace("[[old]]", "[[new]]"), 1)))
            worker.start()
            holder.write(b"- appended by another session\n")
            holder.flush()
            lock_module.flock(holder.fileno(), lock_module.LOCK_UN)
            holder.close()
            worker.join(5)
            cli.append_file(Path("n.md"), "- appended after\n")
            self.assertEqual(note.read_text(), "see [[new]]\n- appended by another session\n- appended after\n")

    def test_append_waiting_on_a_rewrite_lands_in_the_new_note(self) -> None:
        import threading
        import time
        from scripts.obsidian_memory import _rewrite_note, fcntl as lock_module
        if lock_module is None:
            self.skipTest("no advisory locks on this platform")
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            note = vault / "n.md"
            note.write_text("see [[old]]\n")
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            started = threading.Event()

            def slow(text: str):
                started.set()
                time.sleep(0.3)  # the appender queues on the lock meanwhile
                return text.replace("[[old]]", "[[new]]"), 1

            rewriter = threading.Thread(target=_rewrite_note, args=(note, slow))
            rewriter.start()
            started.wait(5)
            appender = threading.Thread(target=cli.append_file, args=(Path("n.md"), "- appended\n"))
            appender.start()
            rewriter.join(5)
            appender.join(5)
            self.assertEqual(note.read_text(), "see [[new]]\n- appended\n")
            self.assertFalse(list(vault.glob(".n.md.*.tmp")))

    def test_dry_run_counts_retired_topics(self) -> None:
        from scripts.obsidian_memory import _archive_stale_topics, build_note_paths
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("demo")
            (vault / paths.topics_dir).mkdir(parents=True)
            (vault / paths.topics_dir / "Old.md").write_text("# Old\n")
            moved = []
            _archive_stale_topics(ObsidianCLI(vault_path=vault, dry_run=True), paths, [], Path("c"), moved)
            self.assertEqual(len(moved), 1)
            self.assertTrue((vault / paths.topics_dir / "Old.md").exists())

    def test_retired_topics_are_reported_so_links_can_follow(self) -> None:
        from scripts.obsidian_memory import _archive_stale_topics, build_note_paths
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("demo")
            (vault / paths.topics_dir).mkdir(parents=True)
            (vault / paths.topics_dir / "Video Export.md").write_text("# Video Export\n")
            (vault / paths.topics_dir / "Testing.md").write_text("# Testing\n")
            moved = []
            cli = ObsidianCLI(vault_path=vault, dry_run=False)
            count = _archive_stale_topics(cli, paths, [paths.topics_dir / "Testing.md"],
                                          Path("Project Memory/demo/Compactions/c"), moved)
            self.assertEqual(count, 1)
            self.assertEqual(moved, [(paths.topics_dir / "Video Export.md",
                                      paths.archived_topics_dir / "Video Export.md")])


class RunSessionStampTests(unittest.TestCase):
    def test_session_comes_from_flag_then_environment(self) -> None:
        from scripts.obsidian_memory import _run_extra
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "env-1"}, clear=False):
            os.environ.pop("OBMEM_SESSION_ID", None)
            self.assertEqual(_run_extra(argparse.Namespace(title=" T ", session="flag-1")),
                             {"title": "T", "session": "flag-1"})
            self.assertEqual(_run_extra(argparse.Namespace(title="T", session=None))["session"], "env-1")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_run_extra(argparse.Namespace(title="T", session=None)), {"title": "T"})


if __name__ == "__main__":
    unittest.main()
