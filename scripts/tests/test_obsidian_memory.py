#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

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
    ensure_related_link,
    parse_tags,
    resolve_note_path,
    sanitize_note_title_component,
    slugify,
    weave_bidirectional,
)


class ObsidianMemoryTests(unittest.TestCase):
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
        self.assertIn("[[MOC]]", home)
        self.assertIn("[[Sequency Home]]", moc)
        self.assertIn("[[Architecture]]", home)
        self.assertIn("[[Roadmap]]", home)
        self.assertIn("[[Current Memory]]", home)
        self.assertIn("[[Architecture]]", moc)
        self.assertIn("[[Current Memory]]", moc)
        self.assertIn("[[MOC]]", architecture)
        self.assertIn("[[Debugging Notes]]", architecture)
        self.assertIn("[[Release Notes]]", roadmap)

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
                "[[Basecamp Home]]",
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
            self.assertIn("[[note-b]]", body_a)
            self.assertIn("[[note-a]]", body_b)

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
        finally:
            if original_state_env is None:
                os.environ.pop("OBMEM_STATE_FILE", None)
            else:
                os.environ["OBMEM_STATE_FILE"] = original_state_env


if __name__ == "__main__":
    unittest.main()
