#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: search Obsidian memory for context.

Reads the hook payload from stdin, extracts the user prompt,
and runs obmem search to surface relevant prior notes.
Output goes to stdout so Claude sees it as hook context.

Requires: obmem CLI installed via pipx.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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

    # Extract user prompt from Claude Code hook payload
    prompt = ""
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            break

    if not prompt:
        return 0

    # Resolve workspace
    cwd = payload.get("cwd") or payload.get("workspace") or "."
    workspace = str(Path(cwd).resolve())

    # Determine project name from workspace directory name
    project_name = Path(workspace).name or "Project"

    # Check if vault is mapped for this workspace
    check = subprocess.run(
        ["obmem", "show-vault", "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        # No vault mapped — silently skip
        return 0

    # Build a short search query from the first ~100 chars of prompt
    query = prompt[:100].strip()
    if not query:
        return 0

    result = subprocess.run(
        ["obmem", "search", "--project", project_name, "--query", query, "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode == 0 and result.stdout.strip():
        print(f"[obsidian-memory] Prior context from Obsidian vault:\n{result.stdout.strip()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
