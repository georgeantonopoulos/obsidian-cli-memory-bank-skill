import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.obsidian_memory import ObsidianCLI, build_parser


class RetrievalBudgetTests(unittest.TestCase):
    def command(self, vault, *argv):
        args = build_parser().parse_args(argv)
        output = io.StringIO()
        with patch('scripts.obsidian_memory.resolve_vault_or_exit', return_value=vault), contextlib.redirect_stdout(output):
            args.func(args)
        return output.getvalue()

    def test_search_default_and_explicit_limits_preserve_archive_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(8):
                (root / f'note-{i}.md').write_text('export progress')
            (root / 'Archive').mkdir()
            (root / 'Archive/old.md').write_text('export progress')
            internal = ObsidianCLI(vault_path=vault, dry_run=False).run('search', 'query=export path:"Project Memory/demo"')
            self.assertEqual(len(internal.splitlines()), 9)
            args = ('search', '--project', 'demo', '--query', 'export')
            default = self.command(vault, *args)
            self.assertIn('Found 8 hits; showing 3.', default)
            self.assertEqual(len(default.splitlines()), 4)
            expanded = self.command(vault, *args, '--limit', '10', '--include-archive')
            self.assertIn('Found 9 hits; showing 9.', expanded)
            self.assertIn('Archive/old.md', expanded)

    def test_read_budget_query_continuation_and_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            text = 'unrelated background\n' * 600 + 'export progress uses measured frames\n' + 'details\n' * 100
            (vault / 'note.md').write_text(text)
            args = ('read-note', '--path', 'note.md')
            default = self.command(vault, *args)
            self.assertTrue(default.startswith(text[:6000]))
            self.assertIn('--offset 6000', default)
            self.assertLess(len(default), 6200)
            focused = self.command(vault, *args, '--query', 'export progress', '--max-chars', '500')
            self.assertIn('export progress uses measured frames', focused)
            self.assertLess(len(focused), 700)
            continued = self.command(vault, *args, '--offset', '6000', '--max-chars', '500')
            self.assertTrue(continued.startswith(text[6000:6500]))
            self.assertEqual(self.command(vault, *args, '--full'), text + '\n')

    def test_query_finds_evidence_late_in_a_long_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / 'note.md').write_text('background ' * 1000 + 'export progress evidence')
            result = self.command(vault, 'read-note', '--path', 'note.md', '--query', 'export progress', '--max-chars', '500')
            self.assertIn('export progress evidence', result)
            self.assertLess(len(result), 700)

    def test_short_note_is_unchanged_and_missing_query_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / 'note.md').write_text('Small complete note.')
            self.assertEqual(self.command(vault, 'read-note', '--path', 'note.md', '--query', 'absent'), 'Small complete note.\n')

    def test_reject_invalid_budgets_and_conflicting_positions(self):
        for args in [
            ['search', '--project', 'demo', '--query', 'x', '--limit', '0'],
            ['read-note', '--path', 'x', '--max-chars', '-1'],
            ['read-note', '--path', 'x', '--offset', '-1'],
            ['read-note', '--path', 'x', '--offset', '2', '--query', 'x'],
        ]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                build_parser().parse_args(args)
