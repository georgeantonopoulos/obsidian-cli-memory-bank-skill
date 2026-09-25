import contextlib
import io
import json
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
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': ''}):
                default = self.command(vault, *args)
            self.assertIn('Found 8 hits; showing 3.', default)
            self.assertEqual(len(default.splitlines()), 4)
            expanded = self.command(vault, *args, '--limit', '10', '--include-archive', '--ranker', 'local')
            self.assertIn('Found 9 hits; showing 9.', expanded)
            self.assertIn('Archive/old.md', expanded)

    def test_jev_reranks_local_shortlist_and_sends_bounded_excerpts(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(5):
                (root / f'note-{i}.md').write_text('export progress\n' + 'detail ' * 500)
            (root / 'Archive').mkdir()
            (root / 'Archive/old.md').write_text('export progress')
            answers = {
                f'candidate_{i}': {'type': 'noul', 'noul': 0.95 if i == 4 else 0.2}
                for i in range(5)
            }
            response = io.BytesIO(json.dumps({'answers': answers}).encode())
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test-key'}), patch(
                'scripts.obsidian_memory.urllib.request.urlopen', return_value=response
            ) as urlopen:
                output = self.command(
                    vault, 'search', '--project', 'demo', '--query', 'export progress',
                    '--ranker', 'auto',
                )
            self.assertIn('showing 3. Ranked by Jev.', output)
            self.assertEqual(len(output.splitlines()), 4)
            self.assertIn('note-4.md', output.splitlines()[1])
            request = urlopen.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.typesafe.ai/v1/systemone')
            payload = json.loads(request.data)
            self.assertEqual(payload['model'], 'jev-latest')
            self.assertEqual(len(payload['questions']), 6)
            best = payload['questions']['best_note']
            self.assertEqual(best['type'], 'choice')
            self.assertEqual(sorted(best['criteria']), [f'note-{i}' for i in range(5)])
            question = payload['questions']['candidate_0']
            self.assertEqual(set(question['criteria']), {'true', 'false'})
            self.assertIn('`excerpt`', question['instructions']['question'])
            self.assertEqual(payload['state'], {'request': 'export progress', 'keywords': 'export progress'})
            excerpt = question['instructions']['excerpt']
            self.assertLessEqual(len(excerpt.split('\n[Excerpt:')[0]), 1200)
            self.assertNotIn('old.md', json.dumps(payload))

    def test_jev_judges_the_intent_when_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(2):
                (root / f'note-{i}.md').write_text('export progress')
            answers = {f'candidate_{i}': {'type': 'noul', 'noul': 0.5} for i in range(2)}
            response = io.BytesIO(json.dumps({'answers': answers}).encode())
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test-key'}), patch(
                'scripts.obsidian_memory.urllib.request.urlopen', return_value=response
            ) as urlopen:
                self.command(
                    vault, 'search', '--project', 'demo', '--query', 'export',
                    '--intent', 'why did the EXR export stall at 90%?', '--ranker', 'jev',
                )
            payload = json.loads(urlopen.call_args.args[0].data)
            self.assertEqual(payload['state']['request'], 'why did the EXR export stall at 90%?')
            self.assertEqual(payload['state']['keywords'], 'export')

    def _jev_search(self, answers, *extra, notes=4):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(notes):
                (root / f'note-{i}.md').write_text('export progress')
            response = io.BytesIO(json.dumps({'answers': answers}).encode())
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test-key'}), patch(
                'scripts.obsidian_memory.urllib.request.urlopen', return_value=response
            ) as urlopen:
                output = self.command(
                    vault, 'search', '--project', 'demo', '--query', 'export', '--ranker', 'jev', *extra,
                )
            return output, urlopen

    def test_confident_best_note_choice_leads(self):
        answers = {f'candidate_{i}': {'type': 'noul', 'noul': 0.9 - i * 0.1} for i in range(4)}
        answers['best_note'] = {'type': 'choice', 'choice': 'note-2', 'confidence': 0.8}
        lines = self._jev_search(answers)[0].splitlines()
        self.assertIn('note-2.md (score', lines[1])
        self.assertTrue(lines[1].endswith('; best)'))
        self.assertIn('note-0.md', lines[2])

    def test_unsure_best_note_choice_keeps_noul_order(self):
        answers = {f'candidate_{i}': {'type': 'noul', 'noul': 0.9 - i * 0.1} for i in range(4)}
        answers['best_note'] = {'type': 'choice', 'choice': 'note-2', 'confidence': 0.3}
        lines = self._jev_search(answers)[0].splitlines()
        self.assertIn('note-0.md', lines[1])
        self.assertNotIn('best', ''.join(lines))

    def test_min_jev_gates_irrelevant_notes(self):
        answers = {f'candidate_{i}': {'type': 'noul', 'noul': 0.6 if i == 1 else 0.05} for i in range(4)}
        output = self._jev_search(answers, '--min-jev', '0.3')[0]
        self.assertIn('showing 1. Ranked by Jev.', output)
        self.assertIn('note-1.md', output)
        answers = {f'candidate_{i}': {'type': 'noul', 'noul': 0.04} for i in range(4)}
        output = self._jev_search(answers, '--min-jev', '0.3')[0]
        self.assertEqual(output.strip(), 'Found 4 hits; none cleared the Jev threshold 0.30 (best 0.04).')

    def test_single_candidate_is_still_judged_for_the_gate(self):
        output, urlopen = self._jev_search(
            {'candidate_0': {'type': 'noul', 'noul': 0.02}}, '--min-jev', '0.3', notes=1,
        )
        self.assertIn('none cleared', output)
        self.assertNotIn('best_note', json.loads(urlopen.call_args.args[0].data)['questions'])

    def test_jev_failure_falls_back_in_auto_and_explicit_mode_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(4):
                (root / f'note-{i}.md').write_text('export progress')
            args = ('search', '--project', 'demo', '--query', 'export')
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test-key'}), patch(
                'scripts.obsidian_memory.urllib.request.urlopen', side_effect=OSError('offline')
            ):
                self.assertIn('Found 4 hits; showing 3.', self.command(vault, *args, '--ranker', 'auto'))
                with self.assertRaisesRegex(RuntimeError, 'Jev ranking request failed'):
                    self.command(vault, *args, '--ranker', 'jev')
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': ''}):
                with self.assertRaisesRegex(RuntimeError, 'requires TYPESAFE_API_KEY'):
                    self.command(vault, *args, '--ranker', 'jev')

    def test_jev_is_off_by_default_and_private_preference_stores_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / 'vault'
            root = vault / 'Project Memory/demo'
            root.mkdir(parents=True)
            for i in range(4):
                (root / f'note-{i}.md').write_text('export progress')
            state = Path(tmp) / 'private-state.json'
            args = ('search', '--project', 'demo', '--query', 'export')
            answers = {
                f'candidate_{i}': {'type': 'noul', 'noul': 0.9 if i == 3 else 0.1}
                for i in range(4)
            }
            response = io.BytesIO(json.dumps({'answers': answers}).encode())
            with patch.dict('os.environ', {
                'TYPESAFE_API_KEY': 'test-key', 'OBMEM_STATE_FILE': str(state),
            }), patch('scripts.obsidian_memory.urllib.request.urlopen', return_value=response) as urlopen:
                self.assertNotIn('Jev', self.command(vault, *args))
                urlopen.assert_not_called()
                self.command(vault, 'set-search-ranker', '--ranker', 'auto')
                self.assertIn('note-3.md', self.command(vault, *args).splitlines()[1])
                self.assertEqual(json.loads(state.read_text())['search_ranker'], 'auto')
                self.assertNotIn('test-key', state.read_text())

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
