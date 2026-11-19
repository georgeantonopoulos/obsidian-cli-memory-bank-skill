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

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    capture_directive,
    claim_summary,
    compact_summary,
    compacted_at,
    digest_compact_summary,
    read_payload,
    recent_prompts,
    record_run,
    truncate,
)

# The summary entry is written around the time this hook starts. The note is
# saved by a detached child process, so the wait never delays the session.
_SUMMARY_WAIT_S = 20.0
_BACKGROUND_FLAG = "--save-compaction"

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
    session = str(payload.get("session_id") or "")
    # Wait for a summary no hook has claimed yet: an older one belongs to a
    # compaction that already has its note, or is being saved by another hook.
    deadline = time.monotonic() + _SUMMARY_WAIT_S
    while True:
        text = compact_summary(path)
        if text and claim_summary(session, text):
            break
        if time.monotonic() >= deadline:
            text = ""
            break
        time.sleep(0.25)
    # One note per compaction, whether from the summary or the fallback below.
    marker = compacted_at(session)
    if marker and not claim_summary(session, f"note-{marker}"):
        return
    topic, digest = digest_compact_summary(text) if text else ("", "")
    if not digest:
        # No new summary (or no PreCompact marker to tell compactions apart): keep the latest requests.
        if not marker:
            return
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
        session=session,
    )
    if result.returncode != 0:
        print(f"[obsidian-memory] compaction note failed (non-blocking): {result.stderr[:200]}", file=sys.stderr)


def start_background_save(payload: dict, workspace: str, project: str) -> None:
    """Save the compaction note in a detached process so the session starts at once."""
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), _BACKGROUND_FLAG],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    child.stdin.write(json.dumps({"payload": payload, "workspace": workspace, "project": project}).encode("utf-8"))
    child.stdin.close()


def background_main() -> int:
    job = json.loads(sys.stdin.read())
    save_compaction_note(job["payload"], job["workspace"], job["project"])
    return 0


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
            start_background_save(payload, workspace, project)
        except Exception:  # never let the note break the session start
            pass
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == [_BACKGROUND_FLAG]:
        try:
            sys.exit(background_main())
        except Exception:
            sys.exit(0)
    sys.exit(main())
