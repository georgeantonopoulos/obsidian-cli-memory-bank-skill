#!/usr/bin/env python3
"""Claude Code hook adapter for Obsidian memory logging.

Docs reference: https://docs.anthropic.com/en/docs/claude-code/hooks
Claude hook payloads are sent to hook commands as JSON via stdin.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.hook_common import (
    content_to_text,
    hook_notice,
    log_turn,
    read_json_payload,
    resolve_path,
    truncate,
)


def _extract_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = [payload.get("messages"), payload.get("input"), payload.get("chat")]
    for candidate in candidates:
        if isinstance(candidate, list):
            out: List[Dict[str, Any]] = []
            for item in candidate:
                if isinstance(item, dict):
                    out.append(item)
            if out:
                return out
    return []


def _load_payload(raw_json: Optional[str]) -> Optional[Dict[str, Any]]:
    raw = raw_json if raw_json is not None else sys.stdin.read().strip()
    if not raw:
        return None
    return read_json_payload(raw)


def extract_prompt(payload: Dict[str, Any]) -> str:
    # Claude's UserPromptSubmit hooks may provide prompt-like fields directly.
    for key in ["prompt", "user_prompt", "message", "input"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(value, 3000)

    messages = _extract_messages(payload)
    user_text: List[str] = []
    for msg in messages:
        role = str(msg.get("role", "")).lower()
        if role in {"user", "human"}:
            user_text.append(content_to_text(msg.get("content")))

    text = "\n\n".join([t for t in user_text if t.strip()])
    return truncate(text or "No user prompt captured.", 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    for key in ["last_assistant_message", "assistant", "response", "output", "tool_response"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(value, 500)

    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        return truncate(f"Claude hook event for tool: {tool_name}", 500)

    messages = _extract_messages(payload)
    assistant_bits: List[str] = []
    for msg in messages:
        role = str(msg.get("role", "")).lower()
        if role in {"assistant", "ai"}:
            assistant_bits.append(content_to_text(msg.get("content")))

    text = "\n\n".join([t for t in assistant_bits if t.strip()])
    return truncate(text or "No assistant summary captured.", 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code notify hook for Obsidian memory bank")
    parser.add_argument("--skill-repo", required=True, help="Path to obsidian-cli-memory-bank-skill repo")
    parser.add_argument("event_json", nargs="?", help="Optional JSON payload (stdin is the default)")
    args = parser.parse_args()

    payload = _load_payload(args.event_json)
    if payload is None:
        hook_notice("obsidian-memory-hook-claude", "received empty/invalid JSON payload; skipping")
        return 0

    event_name = str(payload.get("hook_event_name") or payload.get("type") or payload.get("event") or "").strip()
    if not event_name:
        hook_notice("obsidian-memory-hook-claude", "missing event name; skipping")
        return 0

    # Keep parity with Claude docs: hooks are event-driven by hook_event_name.
    allowed = {
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Notification",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "SessionStart",
        "SessionEnd",
    }
    if event_name not in allowed:
        hook_notice("obsidian-memory-hook-claude", f"unsupported event '{event_name}'; skipping")
        return 0

    workspace_path = resolve_path(payload.get("cwd") or payload.get("workspace") or payload.get("project_path"))
    skill_repo = Path(args.skill_repo).resolve()

    project_name = Path(workspace_path).name or "Project"
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "unknown-session")
    turn_id = f"{session_id}:{event_name}"

    return log_turn(
        prefix="obsidian-memory-hook-claude",
        skill_repo=skill_repo,
        workspace_path=workspace_path,
        project_name=project_name,
        turn_id=turn_id,
        prompt=extract_prompt(payload),
        summary=extract_summary(payload),
        actions=f"Auto-captured from Claude Code hook event '{event_name}'.",
        tags="claude,auto-log",
    )


if __name__ == "__main__":
    sys.exit(main())
