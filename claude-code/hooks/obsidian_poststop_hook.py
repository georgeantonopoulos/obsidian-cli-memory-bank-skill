#!/usr/bin/env python3
"""Claude Code Stop hook: log a run summary to Obsidian memory bank.

The Stop payload carries no prompt, so the prompt, final reply, and edited
files are read from the session transcript. By default only turns that edited
files are logged; set OBMEM_STOP_LOG=all to log every turn, or off to disable.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    last_turn,
    read_payload,
    record_run,
    truncate,
)


def _log_mode() -> str:
    mode = os.environ.get("OBMEM_STOP_LOG", "edits").strip().lower()
    return mode if mode in ("edits", "all", "off") else "edits"


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None or payload.get("stop_hook_active"):
        return 0
    mode = _log_mode()
    if mode == "off":
        return 0

    transcript_path = payload.get("transcript_path")
    turn = last_turn(transcript_path) if isinstance(transcript_path, str) else {
        "prompt": "", "assistant": "", "tools": [], "edited_files": [],
    }
    if mode == "edits" and not turn["edited_files"]:
        return 0

    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    prompt = turn["prompt"]
    summary = payload.get("last_assistant_message") or turn["assistant"]
    if not isinstance(summary, str):
        summary = ""
    edited = turn["edited_files"]
    actions = "Auto-captured from Claude Code Stop event."
    if edited:
        actions += " Files changed: " + ", ".join(edited[:12])
        if len(edited) > 12:
            actions += f" (+{len(edited) - 12} more)"

    result = record_run(
        workspace, project,
        title=prompt or summary or f"Claude Code session in {project}",
        prompt=prompt or "No user prompt captured.",
        summary=truncate(summary, 1500) or "No assistant summary captured.",
        actions=actions,
        tags="claude,auto-log",
    )
    if result.returncode == 0:
        print("[obsidian-memory] Logged run note to Obsidian.", file=sys.stderr)
    else:
        print(f"[obsidian-memory] record-run failed (non-blocking): {result.stderr[:200]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
