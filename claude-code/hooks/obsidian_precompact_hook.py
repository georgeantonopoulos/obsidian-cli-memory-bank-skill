#!/usr/bin/env python3
"""Claude Code PreCompact hook: persist session context to Obsidian before compaction.

Context compaction compresses the conversation history, which may lose details.
This hook captures a snapshot of the session so far as an Obsidian run note,
ensuring important context survives across compaction boundaries.

Reads the hook payload from stdin (includes transcript_summary).
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

    # Extract transcript summary (provided by PreCompact event)
    summary = ""
    for key in ("transcript_summary", "summary", "context"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            summary = value.strip()
            break

    if not summary:
        summary = "Context compaction occurred — no transcript summary available."

    title = truncate(f"Pre-compaction snapshot: {project_name}", 80)

    cmd = [
        "obmem", "record-run",
        "--project", project_name,
        "--title", title,
        "--prompt", "Automatic pre-compaction context capture.",
        "--summary", truncate(summary, 3000),
        "--actions", "Session context persisted to Obsidian before context window compaction.",
        "--tags", "claude,auto-log,compaction",
        "--workspace", workspace,
    ]

    result = subprocess.run(cmd, text=True, capture_output=True, check=False)

    if result.returncode == 0:
        print(
            f"[obsidian-memory] Pre-compaction snapshot saved for {project_name}.",
            file=sys.stderr,
        )
    else:
        print(
            f"[obsidian-memory] pre-compact record-run failed (non-blocking): "
            f"{result.stderr[:200]}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
