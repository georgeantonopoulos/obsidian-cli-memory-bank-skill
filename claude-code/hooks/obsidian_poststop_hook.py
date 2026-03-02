#!/usr/bin/env python3
"""Claude Code Stop hook: log a run summary to Obsidian memory bank.

Reads the hook payload from stdin, extracts session context,
and calls obmem record-run to persist a structured note.

Requires: obmem CLI installed via pipx.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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

    # Resolve workspace
    cwd = payload.get("cwd") or payload.get("workspace") or "."
    workspace = str(Path(cwd).resolve())
    project_name = Path(workspace).name or "Project"

    # Check if vault is mapped
    check = subprocess.run(
        ["obmem", "show-vault", "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        return 0

    # Extract prompt (what the user asked)
    prompt = ""
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            break

    # Extract summary (what the assistant did)
    summary = ""
    for key in ("last_assistant_message", "assistant", "response", "output", "stop_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            summary = value.strip()
            break

    # Extract tool name if present
    tool_name = payload.get("tool_name", "")

    title = truncate(prompt or summary or f"Claude Code session in {project_name}", 80)

    cmd = [
        "obmem", "record-run",
        "--project", project_name,
        "--title", title,
        "--prompt", truncate(prompt or "No user prompt captured.", 3000),
        "--summary", truncate(summary or "No assistant summary captured.", 500),
        "--actions", f"Auto-captured from Claude Code Stop event.{f' Tool: {tool_name}' if tool_name else ''}",
        "--tags", "claude,auto-log",
        "--workspace", workspace,
    ]

    result = subprocess.run(cmd, text=True, capture_output=True, check=False)

    if result.returncode == 0:
        print("[obsidian-memory] Logged run note to Obsidian.", file=sys.stderr)
    else:
        print(f"[obsidian-memory] record-run failed (non-blocking): {result.stderr[:200]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
