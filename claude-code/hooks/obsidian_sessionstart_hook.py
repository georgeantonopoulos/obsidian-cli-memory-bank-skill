#!/usr/bin/env python3
"""Claude Code SessionStart hook: validate Obsidian memory bank connectivity.

Runs obmem doctor at the start of each session to catch issues early
(Obsidian not running, vault unmapped, CLI missing) instead of silently
failing on every subsequent hook invocation.

After a compaction (source "compact") it also saves the summary Claude Code
just wrote as one run note: the request, fixes, findings, pending and current
work. The PreCompact payload has no summary, so this is the first point where
there is one to save.
Output goes to stdout so Claude sees it as hook context.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    capture_directive,
    compact_summary,
    digest_compact_summary,
    read_payload,
    recent_prompts,
    record_run,
    truncate,
)

# The summary entry is written around the time this hook starts: look a few times.
_SUMMARY_WAIT_S = 3.0

# Mandatory: the skill's recall and capture rules must be in context from the first turn.
LOAD_SKILL_DIRECTIVE = (
    "[obsidian-memory] MANDATORY: before your first reply in this session, invoke the "
    "Skill tool with skill \"obsidian-cli-memory-bank\" (once per session, even if the "
    "first task looks self-contained). Then follow its rules for recall and capture."
)


def save_compaction_note(payload: dict, workspace: str, project: str) -> None:
    path = payload.get("transcript_path")
    if not isinstance(path, str):
        return
    text = compact_summary(path)
    deadline = time.monotonic() + _SUMMARY_WAIT_S
    while not text and time.monotonic() < deadline:
        time.sleep(0.25)
        text = compact_summary(path)
    topic, digest = digest_compact_summary(text) if text else ("", "")
    if not digest:
        prompts = recent_prompts(path, limit=5)
        if not prompts:
            return
        digest = "Recent requests before compaction:\n" + "\n".join(f"- {truncate(p, 500)}" for p in prompts)
    result = record_run(
        workspace, project,
        title=f"Compaction: {topic}" if topic else f"Compaction summary: {project}",
        prompt="Summary Claude Code wrote when it compacted the session.",
        summary=digest,
        actions="Saved by the SessionStart hook after context compaction.",
        tags="claude,auto-log,compaction",
        session=str(payload.get("session_id") or ""),
    )
    if result.returncode != 0:
        print(f"[obsidian-memory] compaction note failed (non-blocking): {result.stderr[:200]}", file=sys.stderr)


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0
    # Skips silently when hooks are disabled or no vault is mapped for this project.
    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    try:
        result = subprocess.run(
            ["obmem", "doctor", "--workspace", workspace],
            text=True, capture_output=True, check=False, timeout=30,
        )
        returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        returncode, stdout, stderr = 1, "", str(exc)

    if returncode == 0:
        print(f"[obsidian-memory] Vault healthy for {project}.")
    else:
        # Surface the issue so Claude knows memory hooks may be degraded
        detail = (stderr or "").strip()[:300] or (stdout or "").strip()[:300] or "unknown error"
        print(
            f"[obsidian-memory] WARNING: Obsidian vault health check failed for "
            f"{project}. Memory hooks may not work this session. "
            f"Detail: {detail}"
        )
    print(LOAD_SKILL_DIRECTIVE)
    print(capture_directive(project))
    if payload.get("source") == "compact" and returncode == 0:
        try:
            save_compaction_note(payload, workspace, project)
        except Exception:  # never let the note break the session start
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
