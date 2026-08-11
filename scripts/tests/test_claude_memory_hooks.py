import importlib.util
import unittest
from pathlib import Path


HOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "claude-code"
    / "hooks"
    / "obsidian_preprompt_hook.py"
)
SPEC = importlib.util.spec_from_file_location("obsidian_preprompt_hook", HOOK_PATH)
HOOK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HOOK)


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


if __name__ == "__main__":
    unittest.main()
