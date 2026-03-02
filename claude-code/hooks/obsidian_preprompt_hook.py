#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: search Obsidian memory for context.

Reads the hook payload from stdin, extracts the user prompt,
and runs obmem search to surface relevant prior notes.
Output goes to stdout so Claude sees it as hook context.

Requires: obmem CLI installed via pipx.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Query sanitization (self-contained so the hook file works standalone)
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
    "ok okay yes".split()
)

_FILE_PATH_RE = re.compile(r"@?(?:[A-Za-z]:)?(?:[/\\][\w.\-]+){2,}")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DATE_STAMP_RE = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_NON_ALPHA_RE = re.compile(r"[^A-Za-z0-9\s\-]")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _split_identifier(name: str) -> str:
    """Split a code identifier into words (underscores and camelCase)."""
    parts = name.replace("-", "_").split("_")
    words: list[str] = []
    for part in parts:
        words.extend(_CAMEL_SPLIT_RE.sub(" ", part).split())
    return " ".join(w for w in words if w)


def _sanitize_query(prompt: str, max_words: int = 4) -> str:
    """Extract meaningful search keywords from a raw user prompt."""
    text = prompt
    for pattern in (_URL_RE, _FILE_PATH_RE, _DATE_STAMP_RE):
        text = pattern.sub(" ", text)
    text = _INLINE_CODE_RE.sub(lambda m: " " + _split_identifier(m.group()[1:-1]) + " ", text)
    text = _NON_ALPHA_RE.sub(" ", text)
    words = [w.lower() for w in text.split() if len(w) >= 2]
    keywords = [w for w in words if w not in _STOP_WORDS]
    if not keywords:
        keywords = words[:max_words]
    keywords.sort(key=len, reverse=True)
    return " ".join(keywords[:max_words])


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if not isinstance(payload, dict):
        return 0

    # Extract user prompt from Claude Code hook payload
    prompt = ""
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            break

    if not prompt:
        return 0

    # Resolve workspace
    cwd = payload.get("cwd") or payload.get("workspace") or "."
    workspace = str(Path(cwd).resolve())

    # Determine project name from workspace directory name
    project_name = Path(workspace).name or "Project"

    # Check if vault is mapped for this workspace
    check = subprocess.run(
        ["obmem", "show-vault", "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        # No vault mapped — silently skip
        return 0

    # Extract meaningful keywords instead of passing raw prompt
    query = _sanitize_query(prompt)
    if not query:
        return 0

    result = subprocess.run(
        ["obmem", "search", "--project", project_name, "--query", query, "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode == 0 and result.stdout.strip():
        print(f"[obsidian-memory] Prior context from Obsidian vault:\n{result.stdout.strip()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
