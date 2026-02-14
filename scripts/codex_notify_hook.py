#!/usr/bin/env python3
"""Codex notify hook that writes completed turns to Obsidian memory."""

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
    slug_to_title,
    truncate,
)


def extract_prompt(payload: Dict[str, Any]) -> str:
    messages = payload.get("input-messages")
    if not isinstance(messages, list):
        return "No user prompt captured."

    user_messages: List[str] = []
    for msg in messages:
        if isinstance(msg, str):
            user_messages.append(msg)
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            user_messages.append(content_to_text(msg.get("content")))
            continue
        user_messages.append(content_to_text(msg.get("content")))

    joined = "\n\n".join([m for m in user_messages if m.strip()])
    if not joined:
        return "No user prompt captured."
    return truncate(joined, 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    assistant = payload.get("last-assistant-message")
    if not isinstance(assistant, str) or not assistant.strip():
        return "No assistant summary captured."
    return truncate(assistant, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex notify hook for Obsidian memory bank")
    parser.add_argument("--skill-repo", required=True, help="Path to obsidian-cli-memory-bank-skill repo")
    parser.add_argument("event_json", help="JSON payload from Codex notify")
    args = parser.parse_args()

    payload = read_json_payload(args.event_json)
    if payload is None:
        hook_notice("obsidian-memory-hook", "received invalid JSON payload; skipping")
        return 0
    if payload.get("type") != "agent-turn-complete":
        hook_notice("obsidian-memory-hook", "event is not agent-turn-complete; skipping")
        return 0

    workspace_path = resolve_path(payload.get("cwd"))
    skill_repo = Path(args.skill_repo).resolve()

    project_name = Path(workspace_path).name or "Project"
    prompt = extract_prompt(payload)
    summary = extract_summary(payload)
    turn_id = str(payload.get("turn-id", "unknown-turn"))

    return log_turn(
        prefix="obsidian-memory-hook",
        skill_repo=skill_repo,
        workspace_path=workspace_path,
        project_name=project_name,
        turn_id=turn_id,
        prompt=prompt,
        summary=summary,
        actions="Auto-captured from Codex notify hook on agent-turn-complete.",
        tags="codex,auto-log",
    )


if __name__ == "__main__":
    sys.exit(main())
