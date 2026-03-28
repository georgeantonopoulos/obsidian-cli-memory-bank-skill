#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.obsidian_memory import (
    DEFAULT_AUDIT_EVERY_RUNS,
    PROJECTS_INDEX_PATH,
    _build_or_query,
    _contains_cli_error,
    ConfigStore,
    build_note_paths,
    build_seed_notes,
    ensure_project_dirs,
    parse_tags,
    sanitize_note_title_component,
    slugify,
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
        self.assertIn("[[Architecture]]", moc)
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
        self.assertEqual(len(notes), 9)

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


if __name__ == "__main__":
    unittest.main()
