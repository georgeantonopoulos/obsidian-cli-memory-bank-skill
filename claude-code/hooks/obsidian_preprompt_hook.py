#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: search Obsidian memory for context.

Reads the hook payload from stdin, extracts the user prompt,
and runs obmem search to surface relevant prior notes.
Output goes to stdout so Claude sees it as hook context.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    read_payload,
    redact_secrets,
    truncate,
)

# ---------------------------------------------------------------------------
# Query sanitization
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through about between after before above below up down out off over under "
    "and or but not no nor so yet both either neither each every all any few "
    "more most other some such than too very it its this that these those i me "
    "my we our you your he him his she her they them their what which who whom "
    "how when where why if then else let also just please tell check know make "
    "sure need want like get go see look find use try keep take give show help "
    "ok okay yes oh ooh hi hey thanks thank cool great nice good well now still "
    "anything something everything nothing thing things stuff way lot bit "
    "obvious obviously currently current actually really basically maybe "
    "interested wondering think thought guess seems seem able done doing "
    "improve better best again here there one ones im ive dont cant".split()
)

_FILE_PATH_RE = re.compile(r"@?(?:[A-Za-z]:)?(?:[/\\][\w.\-]+){2,}")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DATE_STAMP_RE = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_NON_ALPHA_RE = re.compile(r"[^A-Za-z0-9\s\-]")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?\n]\s*)([A-Za-z][\w\-]*)")
_SEARCH_HIT_RE = re.compile(r"^\s{2}(Project Memory/.+\.md) \(score \d+(?:; Jev [\d.]+)?(?:; best)?\)$")
_JEV_GATED_RE = re.compile(r"none cleared the Jev threshold")
# Distilled and topical notes answer questions; raw logs mostly repeat them.
_LOW_VALUE_RE = re.compile(r"/(?:Compactions|Archive|Runs)/|/Run Log\.md$")
_MIN_KEYWORDS = 2
_MIN_PROMPT_WORDS = 3
# Jev relevance a note needs before it is injected (TypeSafe's cookbook uses 0.30).
# Unrelated prompts score ~0.02-0.05, related ones 0.5+. Only applies when Jev ranks.
_DEFAULT_JEV_MIN = 0.30


def _jev_min() -> float:
    try:
        value = float(os.environ.get("OBMEM_JEV_MIN", _DEFAULT_JEV_MIN))
    except ValueError:
        return _DEFAULT_JEV_MIN
    return min(max(value, 0.0), 1.0)
_CANDIDATE_LIMIT = 10


def _split_identifier(name: str) -> str:
    """Split a code identifier into words (underscores and camelCase)."""
    parts = name.replace("-", "_").split("_")
    words: list[str] = []
    for part in parts:
        words.extend(_CAMEL_SPLIT_RE.sub(" ", part).split())
    return " ".join(w for w in words if w)


def _is_named(token: str, sentence_starts: set[str]) -> bool:
    """Proper nouns, identifiers, and versions: Jev, TypeSafe, oklch2, ARRI."""
    if any(c.isdigit() for c in token) or any(c.isupper() for c in token[1:]):
        return True
    return token[:1].isupper() and token not in sentence_starts


def _sanitize_query(prompt: str, max_words: int = 4) -> str:
    """Extract meaningful search keywords from a raw user prompt.

    Named things (proper nouns, identifiers in backticks) rank ahead of plain
    words; within each group longer words win.
    """
    text = redact_secrets(prompt).replace("[redacted secret]", " ")
    for pattern in (_URL_RE, _FILE_PATH_RE, _DATE_STAMP_RE):
        text = pattern.sub(" ", text)
    identifiers: set[str] = set()

    def _expand(match: re.Match) -> str:
        words = _split_identifier(match.group()[1:-1])
        identifiers.update(w.lower() for w in words.split())
        return " " + words + " "

    text = _INLINE_CODE_RE.sub(_expand, text)
    sentence_starts = set(_SENTENCE_START_RE.findall(text))
    text = _NON_ALPHA_RE.sub(" ", text)
    seen: set[str] = set()
    ranked: list[tuple[int, int, int, str]] = []
    for position, token in enumerate(text.split()):
        word = token.lower().strip("-")
        if len(word) < 2 or word in seen or word in _STOP_WORDS:
            continue
        seen.add(word)
        named = word in identifiers or _is_named(token, sentence_starts)
        ranked.append((0 if named else 1, -len(word), position, word))
    ranked.sort()
    return " ".join(word for *_rest, word in ranked[:max_words])


def _select_search_hits(output: str, limit: int = 3) -> str:
    """Pick the top note paths.

    Local keyword order is demoted in favour of distilled notes over raw logs;
    a Jev order already judged each note's content, so it is kept as is.
    """
    lines = [line for line in output.splitlines() if _SEARCH_HIT_RE.match(line)]
    if "Ranked by Jev." in output:
        selected = lines[:limit]
    else:
        preferred = [line for line in lines if not _LOW_VALUE_RE.search(_SEARCH_HIT_RE.match(line).group(1))]
        fallback = [line for line in lines if line not in preferred]
        selected = (preferred + fallback)[:limit]
    if not selected:
        return ""
    return f"Showing top {len(selected)} relevant note(s):\n" + "\n".join(selected)


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0

    prompt = ""
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            break
    if not prompt:
        return 0

    query = _sanitize_query(prompt)
    # Short acknowledgements ("ok", "tool loaded") don't warrant a memory lookup.
    if len(prompt.split()) < _MIN_PROMPT_WORDS or len(query.split()) < _MIN_KEYWORDS:
        return 0

    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    # Jev (when the private ranker preference enables it) judges relevance against
    # the redacted request, not just the keywords.
    intent = truncate(redact_secrets(prompt), 500)
    try:
        result = subprocess.run(
            ["obmem", "search", "--project", project, "--query", query,
             "--intent", intent, "--min-jev", f"{_jev_min():.2f}",
             "--limit", str(_CANDIDATE_LIMIT), "--workspace", workspace],
            text=True, capture_output=True, check=False, timeout=20,
        )
        output = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        output = ""
    # Jev judged every candidate irrelevant: stay quiet rather than suggest a search.
    if _JEV_GATED_RE.search(output):
        return 0
    selected_hits = _select_search_hits(output)

    # Always tell the LLM what keywords were searched so it can refine
    # with its own domain knowledge (e.g. searching for "Nuke" or "oklch").
    header = f"[obsidian-memory] Searched Obsidian vault (project: {project}) with keywords: {query}"
    if selected_hits:
        print(f"{header}\n{selected_hits}")
    else:
        print(
            f"{header}\nNo matches. Consider using the obmem skill to search "
            f"with domain-specific keywords (e.g. project name, technology, feature names)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
