#!/usr/bin/env python3
"""Cursor hook adapter for Obsidian memory logging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

from scripts.hook_common import (
    content_to_text,
    hook_notice,
    log_turn,
    read_json_payload,
    resolve_path,
    truncate,
)


def _messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ["messages", "chat_messages", "conversation", "transcript"]:
        value = payload.get(key)
        if isinstance(value, list):
            out = [item for item in value if isinstance(item, dict)]
            if out:
                return out
    return []


def extract_prompt(payload: Dict[str, Any]) -> str:
    msgs = _messages(payload)
    user_parts: List[str] = []
    for msg in msgs:
        role = str(msg.get("role", msg.get("author", ""))).lower()
        if role in {"user", "human"}:
            user_parts.append(content_to_text(msg.get("content") or msg.get("text")))
    prompt = "\n\n".join([t for t in user_parts if t.strip()])
    if not prompt and isinstance(payload.get("prompt"), str):
        prompt = payload["prompt"]
    return truncate(prompt or "No user prompt captured.", 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    for key in ["assistant_message", "last_assistant_message", "response", "output"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(value, 500)
    msgs = _messages(payload)
    assistant_parts: List[str] = []
    for msg in msgs:
        role = str(msg.get("role", msg.get("author", ""))).lower()
        if role in {"assistant", "ai"}:
            assistant_parts.append(content_to_text(msg.get("content") or msg.get("text")))
    summary = "\n\n".join([t for t in assistant_parts if t.strip()])
    return truncate(summary or "No assistant summary captured.", 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor hook for Obsidian memory bank")
    parser.add_argument("--skill-repo", required=True, help="Path to obsidian-cli-memory-bank-skill repo")
    parser.add_argument("event_json", help="JSON payload from Cursor hook")
    args = parser.parse_args()

    payload = read_json_payload(args.event_json)
    if payload is None:
        hook_notice("obsidian-memory-hook-cursor", "received invalid JSON payload; skipping")
        return 0

    event_type = str(payload.get("type", payload.get("event", ""))).lower()
    if event_type and all(token not in event_type for token in ["turn", "message", "complete"]):
        hook_notice("obsidian-memory-hook-cursor", "event is not a completion/turn event; skipping")
        return 0

    workspace = payload.get("workspace") or payload.get("cwd") or payload.get("project")
    workspace_path = resolve_path(workspace)
    skill_repo = Path(args.skill_repo).resolve()

    project_name = Path(workspace_path).name or "Project"
    turn_id = str(payload.get("turnId") or payload.get("turn_id") or payload.get("id") or "unknown-turn")

    return log_turn(
        prefix="obsidian-memory-hook-cursor",
        skill_repo=skill_repo,
        workspace_path=workspace_path,
        project_name=project_name,
        turn_id=turn_id,
        prompt=extract_prompt(payload),
        summary=extract_summary(payload),
        actions="Auto-captured from Cursor hook.",
        tags="cursor,auto-log",
    )


if __name__ == "__main__":
    sys.exit(main())
