#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from scripts.obsidian_memory import (
    DEFAULT_AUDIT_EVERY_RUNS,
    PROJECTS_INDEX_PATH,
    _contains_cli_error,
    ConfigStore,
    build_note_paths,
    build_seed_notes,
    ensure_project_dirs,
    parse_tags,
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

    def test_seed_notes_include_interlinks(self) -> None:
        paths = build_note_paths("Sequency")
        notes = build_seed_notes("Sequency", paths)
        home = notes[paths.home]
        moc = notes[paths.moc]
        self.assertIn("[[MOC]]", home)
        self.assertIn("[[Sequency Home]]", moc)

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


if __name__ == "__main__":
    unittest.main()
