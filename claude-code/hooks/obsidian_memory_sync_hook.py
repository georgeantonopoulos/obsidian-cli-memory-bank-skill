#!/usr/bin/env python3
"""Claude Code PostToolUse hook: sync MEMORY file writes to Obsidian.

Fires after Write or Edit tool calls. Filters for file paths containing
'/memory/' or 'MEMORY.md' to detect Claude's auto-memory saves.
When a memory write is detected, records the content as an Obsidian note
so that project knowledge is mirrored in the vault.

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


def _is_memory_path(file_path: str) -> bool:
    """Check if the file path looks like a Claude auto-memory file."""
    p = file_path.lower()
    return "/memory/" in p or p.endswith("memory.md")


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

    # Only act on Write or Edit tool calls
    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    # Extract file path from tool input
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return 0

    file_path = tool_input.get("file_path", "")
    if not file_path or not _is_memory_path(file_path):
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

    # Read the actual file content from disk (post-write state)
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        content = ""

    if not content.strip():
        return 0

    # Determine which memory file was written
    memory_filename = Path(file_path).name

    title = truncate(f"Memory sync: {memory_filename} ({project_name})", 80)

    cmd = [
        "obmem", "record-run",
        "--project", project_name,
        "--title", title,
        "--prompt", f"Auto-memory file written: {file_path}",
        "--summary", truncate(content, 3000),
        "--actions", f"Claude wrote to {memory_filename}. Content synced to Obsidian vault.",
        "--tags", "claude,auto-log,memory-sync",
        "--workspace", workspace,
    ]

    result = subprocess.run(cmd, text=True, capture_output=True, check=False)

    if result.returncode == 0:
        print(
            f"[obsidian-memory] Synced {memory_filename} to Obsidian vault.",
            file=sys.stderr,
        )
    else:
        print(
            f"[obsidian-memory] memory-sync record-run failed (non-blocking): "
            f"{result.stderr[:200]}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
