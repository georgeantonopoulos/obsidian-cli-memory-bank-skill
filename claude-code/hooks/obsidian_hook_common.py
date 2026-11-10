#!/usr/bin/env python3
"""Shared helpers for the Claude Code Obsidian memory hooks.

Install this file next to the obsidian_*_hook.py scripts. Each hook imports it
from its own directory, so copies and symlinks both work.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_DISABLED_VALUES = frozenset({"0", "off", "false", "no"})


def capture_directive(project: str) -> str:
    """The end-of-turn recording rule, stated wherever the hooks speak to Claude.

    The Stop hook only auto-captures turns that edited files, and its summary is thin,
    so milestones reached in a browser or another tool are lost unless Claude records them.
    """
    return (
        "[obsidian-memory] MANDATORY at the end of every turn that reached a milestone (a decision, a "
        "cause or fix, a verified result, something shipped, published or scheduled), including work done "
        "only in a browser or another tool with no file edits: record it yourself with "
        f"`obmem record-run --project \"{project}\"` before your final reply. The Stop hook only "
        "auto-captures turns that edited files, so do not rely on it."
    )

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
        with open(path, encoding="utf-8", errors="replace") as handle:
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


_TAG_RE = re.compile(r"<[^>]+>")
_TASK_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
_PEER_WRAPPER_RE = re.compile(r"^Another Claude session sent a message:\s*", re.IGNORECASE)
_IDLE_NOTICE_PREFIX = "[Cross-session idle notice]"
_RECORD_RUN_RE = re.compile(r"\bobmem\s+record-run\b")
# Lines `obmem record-run` prints only after the note is written: proof it
# really ran. The later ones survive when long output is cut from the top.
_RECORDED_MARKERS = ("Recorded run note:", "auto-relate:", "Auto-audit:")


def _entry_text(entry: Dict[str, Any]) -> Optional[str]:
    """Plain text of a user entry, or None for tool results."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return None


def _strip_tags(text: str) -> str:
    return " ".join(_TAG_RE.sub(" ", _PEER_WRAPPER_RE.sub("", text)).split())


def turn_start_prompt(entry: Dict[str, Any]) -> str:
    """The prompt text if this entry starts a turn, else ''.

    A turn starts on a typed prompt and also on anything that wakes the session
    by itself: a message from another session, a background task notice, an idle
    notice. Those used to be skipped (they start with '<' or are meta entries),
    so the Stop hook paired the reply to a message from another session with the last typed
    prompt and re-logged every edit since it.
    """
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return ""
    text = _entry_text(entry)
    if text is None:
        return ""
    origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
    kind = origin.get("kind")
    if text.startswith("[Request interrupted"):
        return ""
    if kind == "peer":
        body = str(origin.get("body") or "").strip() or _strip_tags(text)
        return f"Message from {origin.get('name') or 'another session'}: {body}"
    if kind == "task-notification":
        match = _TASK_SUMMARY_RE.search(text)
        return "Background task: " + (" ".join(match.group(1).split()) if match else _strip_tags(text))
    if kind == "human":
        if entry.get("isMeta"):
            return ""
        if text.startswith("<") and not text.startswith("<pasted"):
            return _strip_tags(text)
        return text
    if entry.get("isMeta"):
        return text if text.startswith(_IDLE_NOTICE_PREFIX) else ""
    # Transcripts without an origin field: typed prompts only.
    if text.startswith("<") and not text.startswith("<pasted"):
        return ""
    return text


def _is_typed(entry: Dict[str, Any]) -> bool:
    if entry.get("isMeta"):
        return False  # idle notices and other injected entries are not typed
    origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
    return origin.get("kind") in (None, "human")


def _result_text(block: Dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _after_finished_reply(entries: List[Dict[str, Any]], index: int) -> bool:
    """True when the session was idle before this entry (the last reply did not end in a tool call).

    A message or task notice that lands mid-turn is delivered between a tool
    result and the next reply; it is part of that turn, not the start of one.
    """
    for entry in reversed(entries[:index]):
        if entry.get("isSidechain"):
            continue
        if entry.get("type") == "user" and _entry_text(entry) is None:
            return False  # a tool result: the turn was still running
        if entry.get("type") == "assistant":
            content = (entry.get("message") or {}).get("content") if isinstance(entry.get("message"), dict) else None
            blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
            return not blocks or blocks[-1].get("type") != "tool_use"
    return True


def last_turn(transcript_path: str) -> Dict[str, Any]:
    """Summarise the latest turn: prompt, final assistant text, edited files.

    ``recorded`` is True when the turn already ran ``obmem record-run`` itself;
    ``start_id`` identifies the entry that started the turn.
    """
    entries = _load_transcript(transcript_path)
    start = None
    prompt = ""
    for index in range(len(entries) - 1, -1, -1):
        prompt = turn_start_prompt(entries[index])
        if prompt and (_is_typed(entries[index]) or _after_finished_reply(entries, index)):
            start = index
            break
    if start is None:
        return {"prompt": "", "assistant": "", "tools": [], "edited_files": [],
                "recorded": False, "start_id": ""}
    tools: List[str] = []
    edited: List[str] = []
    assistant_text = ""
    recorded = False
    record_ids: set = set()
    for entry in entries[start + 1:]:
        if entry.get("isSidechain"):
            continue
        if entry.get("type") == "user":
            # Only a record-run that actually wrote a note counts (not a grep or echo of the text).
            content = (entry.get("message") or {}).get("content") if isinstance(entry.get("message"), dict) else None
            for block in content if isinstance(content, list) else []:
                if (isinstance(block, dict) and block.get("type") == "tool_result"
                        and str(block.get("tool_use_id", "")) in record_ids and not block.get("is_error")
                        and any(marker in _result_text(block) for marker in _RECORDED_MARKERS)):
                    recorded = True
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                tools.append(name)
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
                if name in EDIT_TOOLS and file_path and file_path not in edited:
                    edited.append(str(file_path))
                if name == "Bash" and _RECORD_RUN_RE.search(str(tool_input.get("command", ""))):
                    record_ids.add(str(block.get("id", "")))
            elif block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                assistant_text = block["text"].strip()
    first = entries[start]
    return {
        "prompt": prompt,
        "assistant": assistant_text,
        "tools": tools,
        "edited_files": edited,
        "recorded": recorded,
        "start_id": str(first.get("uuid") or first.get("promptId") or f"line-{start}"),
    }


# ---------------------------------------------------------------------------
# Stop-hook de-duplication: one auto note per turn, even if Stop fires again
# ---------------------------------------------------------------------------

_SEEN_MAX_AGE = 14 * 24 * 3600


def _seen_dir() -> Path:
    override = os.environ.get("OBMEM_STOP_STATE", "").strip()
    return Path(override) if override else Path.home() / ".cache" / "obmem" / "stop-hook-seen"


def _seen_file(session_id: str) -> Path:
    # One small file per session: concurrent sessions never rewrite each other's state.
    return _seen_dir() / (hashlib.sha1(session_id.encode("utf-8")).hexdigest() + ".txt")


def turn_already_logged(session_id: str, start_id: str) -> bool:
    if not session_id or not start_id:
        return False
    try:
        return _seen_file(session_id).read_text(encoding="utf-8").strip() == start_id
    except (OSError, ValueError):
        return False


def mark_turn_logged(session_id: str, start_id: str) -> None:
    if not session_id or not start_id:
        return
    try:
        target = _seen_file(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(start_id, encoding="utf-8")
        tmp.replace(target)
        cutoff = time.time() - _SEEN_MAX_AGE
        for old in target.parent.glob("*.txt"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
    except OSError:
        pass


def record_run(workspace: str, project: str, *, title: str, prompt: str, summary: str,
               actions: str, tags: str, session: str = "") -> subprocess.CompletedProcess:
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
    if session:
        cmd += ["--session", session]
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))
