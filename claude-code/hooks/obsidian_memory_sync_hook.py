#!/usr/bin/env python3
"""Claude Code PostToolUse hook: sync MEMORY file writes to Obsidian.

Fires after Write or Edit tool calls. Only Claude Code's own auto-memory
files (~/.claude/projects/<project>/memory/*.md) are mirrored; other paths
that merely contain "memory" are ignored.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import active_context, read_payload, record_run  # noqa: E402


def _is_memory_path(file_path: str) -> bool:
    """True for Claude Code auto-memory files: ~/.claude/projects/*/memory/*.md."""
    parts = Path(file_path).expanduser().parts
    if not file_path.lower().endswith(".md") or len(parts) < 4:
        return False
    for index in range(len(parts) - 3):
        if parts[index] == ".claude" and parts[index + 1] == "projects" and "memory" in parts[index + 3:-1]:
            return True
    return False


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return 0

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return 0
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path or not _is_memory_path(file_path):
        return 0

    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    # Read the actual file content from disk (post-write state)
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    if not content.strip():
        return 0

    memory_filename = Path(file_path).name
    result = record_run(
        workspace, project,
        title=f"Memory sync: {memory_filename} ({project})",
        prompt=f"Auto-memory file written: {file_path}",
        summary=content,
        actions=f"Claude wrote to {memory_filename}. Content synced to Obsidian vault.",
        tags="claude,auto-log,memory-sync",
    )
    if result.returncode == 0:
        print(f"[obsidian-memory] Synced {memory_filename} to Obsidian vault.", file=sys.stderr)
    else:
        print(
            f"[obsidian-memory] memory-sync record-run failed (non-blocking): {result.stderr[:200]}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
