#!/usr/bin/env python3
"""Claude Code hook adapter for Obsidian memory logging."""

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


def extract_prompt(payload: Dict[str, Any]) -> str:
    messages = _extract_messages(payload)
    user_text: List[str] = []
    for msg in messages:
        role = str(msg.get("role", "")).lower()
        if role in {"user", "human"}:
            user_text.append(content_to_text(msg.get("content")))
    if not user_text and isinstance(payload.get("prompt"), str):
        user_text = [payload["prompt"]]
    text = "\n\n".join([t for t in user_text if t.strip()])
    return truncate(text or "No user prompt captured.", 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    for key in ["last_assistant_message", "assistant", "response", "output"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(value, 500)
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
    parser.add_argument("event_json", help="JSON payload from Claude Code hook")
    args = parser.parse_args()

    payload = read_json_payload(args.event_json)
    if payload is None:
        hook_notice("obsidian-memory-hook-claude", "received invalid JSON payload; skipping")
        return 0

    event_type = str(payload.get("type", payload.get("event", ""))).lower()
    if event_type and "turn" not in event_type and "message" not in event_type and "complete" not in event_type:
        hook_notice("obsidian-memory-hook-claude", "event is not a completion/turn event; skipping")
        return 0

    workspace = payload.get("cwd") or payload.get("workspace") or payload.get("project_path")
    workspace_path = resolve_path(workspace)
    skill_repo = Path(args.skill_repo).resolve()

    project_name = Path(workspace_path).name or "Project"
    turn_id = str(payload.get("turn_id") or payload.get("turn-id") or payload.get("id") or "unknown-turn")

    return log_turn(
        prefix="obsidian-memory-hook-claude",
        skill_repo=skill_repo,
        workspace_path=workspace_path,
        project_name=project_name,
        turn_id=turn_id,
        prompt=extract_prompt(payload),
        summary=extract_summary(payload),
        actions="Auto-captured from Claude Code hook.",
        tags="claude,auto-log",
    )


if __name__ == "__main__":
    sys.exit(main())
