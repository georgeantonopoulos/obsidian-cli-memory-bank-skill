#!/usr/bin/env python3
"""
Codex notify hook that writes each completed turn to Obsidian memory bank.

Codex `notify` invokes this script with a JSON payload argument.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def hook_notice(message: str) -> None:
    # Keep hook execution transparent in Codex logs without breaking runtime flow.
    print(f"[obsidian-memory-hook] {message}", file=sys.stderr, flush=True)


def truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def slug_to_title(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s\-_/]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "Codex Turn Log"
    words = cleaned.split(" ")
    return " ".join(words[:8])


def _content_to_text(content: Any) -> str:
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
        # Backward/forward compatibility if shape ever expands.
        if msg.get("role") == "user":
            user_messages.append(_content_to_text(msg.get("content")))
            continue
        user_messages.append(_content_to_text(msg.get("content")))
    joined = "\n\n".join([m for m in user_messages if m.strip()])
    if not joined:
        return "No user prompt captured."
    return truncate(joined, 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    assistant = payload.get("last-assistant-message")
    if not isinstance(assistant, str) or not assistant.strip():
        return "No assistant summary captured."
    return truncate(assistant, 500)


def run_obsidian_memory(skill_repo: Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    script = skill_repo / "scripts" / "obsidian_memory.py"
    cmd = ["python3", str(script), *args]
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def extract_recorded_note_path(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Recorded run note:"):
            return line.split(":", 1)[1].strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex notify hook for Obsidian memory bank")
    parser.add_argument("--skill-repo", required=True, help="Path to obsidian-cli-memory-bank-skill repo")
    parser.add_argument("event_json", help="JSON payload from Codex notify")
    args = parser.parse_args()

    try:
        payload = json.loads(args.event_json)
    except json.JSONDecodeError:
        hook_notice("received invalid JSON payload; skipping")
        return 0
    if not isinstance(payload, dict):
        hook_notice("received non-dict payload; skipping")
        return 0
    if payload.get("type") != "agent-turn-complete":
        hook_notice("event is not agent-turn-complete; skipping")
        return 0

    workspace = payload.get("cwd")
    if not isinstance(workspace, str) or not workspace:
        workspace = "."
    workspace_path = str(Path(workspace).resolve())
    skill_repo = Path(args.skill_repo).resolve()
    hook_notice(f"running for workspace: {workspace_path}")

    show = run_obsidian_memory(
        skill_repo,
        ["show-vault", "--workspace", workspace_path],
    )
    if show.returncode != 0:
        # No vault mapping for this workspace.
        hook_notice("no vault mapping found; skipping")
        return 0

    project_name = Path(workspace_path).name or "Project"
    prompt = extract_prompt(payload)
    summary = extract_summary(payload)
    turn_id = payload.get("turn-id", "unknown-turn")
    title = slug_to_title(f"Codex Turn {turn_id} {prompt}")

    record = run_obsidian_memory(
        skill_repo,
        [
            "record-run",
            "--project",
            project_name,
            "--title",
            title,
            "--prompt",
            prompt,
            "--summary",
            summary,
            "--actions",
            "Auto-captured from Codex notify hook on agent-turn-complete.",
            "--tags",
            "codex,auto-log",
            "--workspace",
            workspace_path,
        ],
    )
    # Never block Codex execution on hook issues.
    if record.returncode != 0:
        hook_notice("record-run failed; continuing without blocking")
        return 0
    note_path = extract_recorded_note_path(record.stdout)
    if note_path:
        hook_notice(f"logged run note: {note_path}")
    else:
        hook_notice("logged run note")
    return 0


if __name__ == "__main__":
    sys.exit(main())
