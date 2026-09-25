#!/usr/bin/env python3
"""Shared helpers for the Claude Code Obsidian memory hooks.

Install this file next to the obsidian_*_hook.py scripts. Each hook imports it
from its own directory, so copies and symlinks both work.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_DISABLED_VALUES = frozenset({"0", "off", "false", "no"})

# ---------------------------------------------------------------------------
# Secret redaction: nothing that looks like a credential may reach a search
# query, a Jev request, or a vault note.
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = (
    # Known credential prefixes (Anthropic, OpenAI, GitHub, Slack, AWS, Google,
    # GitLab, Stripe, TypeSafe-style apikey_...)
    re.compile(
        r"\b(?:sk-(?:ant-)?[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|xox[abposr]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}"
        r"|glpat-[A-Za-z0-9_\-]{20,}|[rs]k_(?:live|test)_[A-Za-z0-9]{16,}|apikey_[A-Za-z0-9_\-]{16,})"
    ),
    # Authorization headers
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}=*"),
    # key=value / key: value where the key names a secret
    re.compile(
        r"(?i)\b([A-Za-z0-9_]*(?:api[_-]?key|token|secret|passw(?:or)?d|credential)[A-Za-z0-9_]*)"
        r"(\s*[=:]\s*)[\"']?[^\s\"']{8,}[\"']?"
    ),
    # Long opaque tokens: 32+ chars mixing letters and digits (hex digests, JWT parts,
    # keys). Hyphens are excluded so dated note slugs and UUIDs survive.
    re.compile(r"\b(?=[A-Za-z0-9_]*\d)(?=[A-Za-z0-9_]*[A-Za-z])[A-Za-z0-9_]{32,}\b"),
)
REDACTED = "[redacted secret]"


def redact_secrets(text: str) -> str:
    """Replace anything that looks like a credential with a placeholder."""
    if not text:
        return text
    text = _SECRET_PATTERNS[0].sub(REDACTED, text)
    text = _SECRET_PATTERNS[1].sub(REDACTED, text)
    text = _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _SECRET_PATTERNS[3].sub(REDACTED, text)
    return text


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


# ---------------------------------------------------------------------------
# Payload, project identity, and opt-out
# ---------------------------------------------------------------------------


def read_payload(raw: str) -> Optional[Dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _git_toplevel(path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            text=True, capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = result.stdout.strip()
    return top if result.returncode == 0 and top else None


def project_root(payload: Dict[str, Any]) -> str:
    """Stable project root: the directory Claude was launched in, not the current cwd.

    The cwd moves when Claude cds into a subfolder, which used to file notes under
    a different project. Prefer CLAUDE_PROJECT_DIR, then the git toplevel of cwd.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env_root and Path(env_root).is_dir():
        return str(Path(env_root).resolve())
    cwd = str(Path(payload.get("cwd") or payload.get("workspace") or ".").resolve())
    return _git_toplevel(cwd) or cwd


def project_name(root: str) -> str:
    return Path(root).name or "Project"


def hooks_disabled(root: str) -> bool:
    """Opt out globally with OBMEM_HOOKS=off, or per project with a .obmem-off file."""
    if os.environ.get("OBMEM_HOOKS", "").strip().lower() in _DISABLED_VALUES:
        return True
    return (Path(root) / ".obmem-off").exists()


def vault_mapped(workspace: str) -> bool:
    try:
        check = subprocess.run(
            ["obmem", "show-vault", "--workspace", workspace],
            text=True, capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return check.returncode == 0


def active_context(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return (workspace, project name) when the hooks should run, else None."""
    root = project_root(payload)
    if hooks_disabled(root) or not vault_mapped(root):
        return None
    return root, project_name(root)


# ---------------------------------------------------------------------------
# Transcript reading (Stop and PreCompact payloads carry no prompt text)
# ---------------------------------------------------------------------------


def _load_transcript(path: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []
    return entries


def _user_prompt_text(entry: Dict[str, Any]) -> str:
    """Text of a real user prompt entry, or '' for tool results and meta entries."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        text = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    else:
        return ""
    # Local slash-command wrappers and hook echoes are not prompts.
    if text.startswith("<") and not text.startswith("<pasted"):
        return ""
    return text


def recent_prompts(transcript_path: str, limit: int = 5) -> List[str]:
    prompts = [p for p in map(_user_prompt_text, _load_transcript(transcript_path)) if p]
    return prompts[-limit:]


def last_turn(transcript_path: str) -> Dict[str, Any]:
    """Summarise the latest turn: prompt, final assistant text, and edited files."""
    entries = _load_transcript(transcript_path)
    start = None
    for index in range(len(entries) - 1, -1, -1):
        if _user_prompt_text(entries[index]):
            start = index
            break
    if start is None:
        return {"prompt": "", "assistant": "", "tools": [], "edited_files": []}
    tools: List[str] = []
    edited: List[str] = []
    assistant_text = ""
    for entry in entries[start + 1:]:
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        for block in (entry.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                tools.append(name)
                file_path = (block.get("input") or {}).get("file_path") or (block.get("input") or {}).get("notebook_path")
                if name in EDIT_TOOLS and file_path and file_path not in edited:
                    edited.append(str(file_path))
            elif block.get("type") == "text" and block.get("text", "").strip():
                assistant_text = block["text"].strip()
    return {
        "prompt": _user_prompt_text(entries[start]),
        "assistant": assistant_text,
        "tools": tools,
        "edited_files": edited,
    }


def record_run(workspace: str, project: str, *, title: str, prompt: str, summary: str,
               actions: str, tags: str) -> subprocess.CompletedProcess:
    cmd = [
        "obmem", "record-run",
        "--project", project,
        "--title", truncate(redact_secrets(title), 80),
        "--prompt", truncate(redact_secrets(prompt), 3000),
        "--summary", truncate(redact_secrets(summary), 3000),
        "--actions", truncate(redact_secrets(actions), 1000),
        "--tags", tags,
        "--workspace", workspace,
    ]
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))
