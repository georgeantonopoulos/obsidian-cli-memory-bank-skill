"""obmem ask: one follow-up question to memory, with a found/weak/nothing verdict."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.obsidian_memory import _ask_keywords, _ask_verdict, build_parser


def _vault(tmp: str) -> Path:
    vault = Path(tmp)
    notes = {
        "Project Memory/demo/Decisions.md":
            "# Decisions\n\n" + "filler line about other things\n" * 200
            + "- Read cache: store half float; full float doubled the disk cache size.\n",
        "Project Memory/demo/Runs/2026-11-01-1000-cache-notes.md":
            "# Cache notes\n\nThe disk cache was discussed; no decision yet.\n",
        "Project Memory/demo/MOC.md": "# MOC\n\n- disk cache float decision (see Decisions)\n",
    }
    for rel, text in notes.items():
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(text, encoding="utf-8")
    return vault


def _ask(vault: Path, *extra: str) -> str:
    args = build_parser().parse_args(["ask", "--project", "Demo", "--ranker", "local", *extra])
    with patch("scripts.obsidian_memory.resolve_vault_or_exit", return_value=vault), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        args.func(args)
    return out.getvalue()


class AskTests(unittest.TestCase):
    def test_keywords_drop_question_words(self) -> None:
        self.assertEqual(_ask_keywords("Should the read cache store half or full float?"),
                         ["read", "cache", "store", "half", "full", "float"])

    def test_verdict_needs_most_words_on_one_line_and_relevance(self) -> None:
        self.assertEqual(_ask_verdict(0.9, 0.75, 4), "found")
        self.assertEqual(_ask_verdict(0.9, 0.25, 4), "weak")
        self.assertEqual(_ask_verdict(0.3, 1.0, 4), "weak")
        self.assertEqual(_ask_verdict(0.9, 1.0, 1), "found")
        self.assertEqual(_ask_verdict(0.5, 1.0, 1), "weak")

    def test_without_jev_the_verdict_is_left_to_the_agent(self) -> None:
        self.assertEqual(_ask_verdict(None, 1.0, 4), "unchecked")

    def test_found_centres_the_excerpt_on_the_decision_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _ask(_vault(tmp), "--question", "what float does the disk cache store?",
                       "--max-chars", "400")
        self.assertIn("Status: unchecked", out)
        self.assertIn("store half float", out)
        self.assertIn("Project Memory/demo/Decisions.md", out)

    def test_index_pages_are_read_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _ask(_vault(tmp), "--question", "what float does the disk cache store?", "--notes", "2")
        read = out.split("Read (pass")[1].split("\n---")[0]
        self.assertNotIn("MOC.md", read)

    def test_exclude_skips_notes_already_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _ask(_vault(tmp), "--question", "what float does the disk cache store?",
                       "--exclude", "Project Memory/demo/Decisions.md", "--exclude", "MOC", "--notes", "1")
        self.assertNotIn("demo/Decisions.md", out)
        self.assertIn("cache-notes.md", out)

    def test_nothing_when_no_note_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _ask(_vault(tmp), "--question", "which licence did we pick for kubernetes?")
        self.assertIn("Status: nothing", out)
        self.assertIn("ask the user", out)

    def test_jev_verdict_reaches_the_status_line(self) -> None:
        def fake_rerank(_cli, _query, candidates, _key, _intent=""):
            return [(score, path, 0.95 if "Decisions" in path else 0.1, "Decisions" in path)
                    for score, path in candidates]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict("os.environ", {"TYPESAFE_API_KEY": "test"}), \
                patch("scripts.obsidian_memory._jev_rerank", side_effect=fake_rerank):
            vault = _vault(tmp)
            args = build_parser().parse_args(["ask", "--project", "Demo", "--ranker", "jev",
                                              "--question", "what float does the disk cache store?"])
            with patch("scripts.obsidian_memory.resolve_vault_or_exit", return_value=vault), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                args.func(args)
        self.assertIn("Status: found (Jev 0.95", out.getvalue())

    def test_query_overrides_question_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _ask(_vault(tmp), "--question", "how big is it on disk?", "--query", "half float")
        self.assertIn("Searched for: half float", out)


if __name__ == "__main__":
    unittest.main()
