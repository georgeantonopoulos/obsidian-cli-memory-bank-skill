#!/usr/bin/env python3
"""Claude Code PreCompact hook: persist session context to Obsidian before compaction.

Context compaction compresses the conversation history, which may lose details.
This hook captures a snapshot of the session so far as an Obsidian run note,
ensuring important context survives across compaction boundaries. The PreCompact
payload has no summary, so the recent prompts are read from the transcript.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    read_payload,
    recent_prompts,
    record_run,
    truncate,
)


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0
    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    summary = ""
    for key in ("transcript_summary", "summary", "context"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            summary = value.strip()
            break
    if not summary and isinstance(payload.get("transcript_path"), str):
        prompts = recent_prompts(payload["transcript_path"], limit=5)
        if prompts:
            summary = "Recent requests before compaction:\n" + "\n".join(
                f"- {truncate(p, 500)}" for p in prompts
            )
    if not summary:
        summary = "Context compaction occurred — no transcript summary available."

    result = record_run(
        workspace, project,
        title=f"Pre-compaction snapshot: {project}",
        prompt="Automatic pre-compaction context capture.",
        summary=summary,
        actions="Session context persisted to Obsidian before context window compaction.",
        tags="claude,auto-log,compaction",
    )
    if result.returncode == 0:
        print(f"[obsidian-memory] Pre-compaction snapshot saved for {project}.", file=sys.stderr)
    else:
        print(
            f"[obsidian-memory] pre-compact record-run failed (non-blocking): {result.stderr[:200]}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
