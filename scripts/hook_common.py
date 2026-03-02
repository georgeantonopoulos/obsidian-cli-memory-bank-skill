#!/usr/bin/env python3
"""Shared utilities for Obsidian memory notify adapters."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def hook_notice(prefix: str, message: str) -> None:
    print(f"[{prefix}] {message}", file=sys.stderr, flush=True)


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

# Patterns stripped before keyword extraction.
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


def sanitize_query(prompt: str, max_words: int = 4) -> str:
    """Extract meaningful search keywords from a raw user prompt.

    Strips file paths, @-mentions, URLs, date stamps, inline code, and
    common stop words so that Obsidian CLI search receives only content
    keywords likely to match note text.  Keeps at most *max_words*
    keywords, preferring longer (more specific) words since Obsidian
    search AND-matches all terms.
    """
    text = prompt
    for pattern in (_URL_RE, _FILE_PATH_RE, _DATE_STAMP_RE):
        text = pattern.sub(" ", text)
    # Replace inline code with its constituent words (split on underscores
    # and camelCase boundaries) so function names survive as keywords.
    text = _INLINE_CODE_RE.sub(lambda m: " " + _split_identifier(m.group()[1:-1]) + " ", text)
    text = _NON_ALPHA_RE.sub(" ", text)
    words = [w.lower() for w in text.split() if len(w) >= 2]
    keywords = [w for w in words if w not in _STOP_WORDS]
    if not keywords:
        keywords = words[:max_words]
    # Prefer longer words — they tend to be more specific and match better
    # with Obsidian's AND-style search.
    keywords.sort(key=len, reverse=True)
    return " ".join(keywords[:max_words])


def truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def slug_to_title(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s\-_/]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "Agent Turn Log"
    words = cleaned.split(" ")
    return " ".join(words[:8])


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


def run_obsidian_memory(skill_repo: Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    script = skill_repo / "scripts" / "obsidian_memory.py"
    cmd = ["python3", str(script), *args]
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def extract_recorded_note_path(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Recorded run note:"):
            return line.split(":", 1)[1].strip()
    return ""


def resolve_path(value: Optional[str], default: str = ".") -> str:
    if not value:
        value = default
    return str(Path(value).resolve())


def read_json_payload(event_json: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(event_json)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def log_turn(
    *,
    prefix: str,
    skill_repo: Path,
    workspace_path: str,
    project_name: str,
    turn_id: str,
    prompt: str,
    summary: str,
    actions: str,
    tags: str,
) -> int:
    hook_notice(prefix, f"running for workspace: {workspace_path}")

    show = run_obsidian_memory(skill_repo, ["show-vault", "--workspace", workspace_path])
    if show.returncode != 0:
        hook_notice(prefix, "no vault mapping found; skipping")
        return 0

    title = slug_to_title(f"{project_name} Turn {turn_id} {prompt}")

    record = run_obsidian_memory(
        skill_repo,
        [
            "record-run",
            "--project",
            project_name,
            "--title",
            title,
            "--prompt",
            truncate(prompt or "No user prompt captured.", 3000),
            "--summary",
            truncate(summary or "No assistant summary captured.", 500),
            "--actions",
            actions,
            "--tags",
            tags,
            "--workspace",
            workspace_path,
        ],
    )

    if record.returncode != 0:
        hook_notice(prefix, "record-run failed; continuing without blocking")
        return 0

    note_path = extract_recorded_note_path(record.stdout)
    if note_path:
        hook_notice(prefix, f"logged run note: {note_path}")
    else:
        hook_notice(prefix, "logged run note")
    return 0
