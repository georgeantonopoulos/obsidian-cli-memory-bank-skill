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
