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
    _has_link_to,
    _parse_related_arg,
    _parse_search_output_paths,
    cmd_compact_project,
    ConfigStore,
    ObsidianCLI,
    build_note_paths,
    build_seed_notes,
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

    def test_ensure_project_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            paths = build_note_paths("Sequency")
            ensure_project_dirs(vault, paths, dry_run=False)
            self.assertTrue((vault / "Project Memory" / "sequency").is_dir())
            self.assertTrue((vault / "Project Memory" / "sequency" / "Runs").is_dir())

    def test_projects_index_path(self) -> None:
        self.assertEqual(PROJECTS_INDEX_PATH.as_posix(), "Project Memory/Projects Index.md")

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
