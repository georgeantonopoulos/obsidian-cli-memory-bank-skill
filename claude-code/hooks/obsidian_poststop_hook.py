#!/usr/bin/env python3
"""Claude Code Stop hook: log a run summary to Obsidian memory bank.

The Stop payload carries no prompt, so the prompt, final reply, and edited
files are read from the session transcript. By default only turns that edited
files are logged; set OBMEM_STOP_LOG=all to log every turn, or off to disable.
Turns whose only edits match ~/.config/obmem/capture-ignore.txt are skipped.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import (  # noqa: E402
    active_context,
    is_answer_prompt,
    is_antigravity_payload,
    is_progress_reply,
    is_wrapper_prompt,
    last_turn,
    mark_turn_logged,
    only_ignored_edits,
    read_payload,
    record_run,
    reply_title,
    session_id_from,
    strip_reminders,
    transcript_path_from,
    truncate,
    turn_already_logged,
)


def _log_mode() -> str:
    mode = os.environ.get("OBMEM_STOP_LOG", "edits").strip().lower()
    return mode if mode in ("edits", "all", "off") else "edits"


# Antigravity turns often answer, plan or review without editing a file, and
# Antigravity agents rarely record those themselves, so a reply this long is
# kept even with no edits. Claude Code agents record such turns by hand.
_SUBSTANTIAL_REPLY_CHARS = 400


def _substantial(payload: dict, turn: dict) -> bool:
    reply = payload.get("last_assistant_message") or turn.get("assistant") or ""
    if not isinstance(reply, str):
        return False
    text = " ".join(strip_reminders(reply).split())
    return len(text) >= _SUBSTANTIAL_REPLY_CHARS and not is_progress_reply(text)


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0
    antigravity = is_antigravity_payload(payload)

    def _allow_stop() -> int:
        if antigravity:
            print(json.dumps({"decision": "allow"}))
        return 0

    if payload.get("stop_hook_active"):
        return _allow_stop()
    if antigravity:
        reason = str(payload.get("terminationReason") or "")
        if reason and reason != "NO_TOOL_CALL":
            return _allow_stop()
    mode = _log_mode()
    if mode == "off":
        return _allow_stop()

    transcript_path = transcript_path_from(payload)
    turn = last_turn(transcript_path) if isinstance(transcript_path, str) else {
        "prompt": "", "assistant": "", "tools": [], "edited_files": [],
        "recorded": False, "start_id": "",
    }
    if mode == "edits" and not turn["edited_files"] and not (
            antigravity and _substantial(payload, turn)):
        return _allow_stop()
    # Edits only to files the user listed as their own record: a note would copy them.
    if only_ignored_edits(turn["edited_files"]):
        return _allow_stop()
    # The agent already wrote a note for this turn; a second, thinner one is noise.
    if turn.get("recorded"):
        return _allow_stop()
    session_id = session_id_from(payload)
    start_id = str(turn.get("start_id") or "")
    if turn_already_logged(session_id, start_id):
        return _allow_stop()

    context = active_context(payload)
    if context is None:
        return _allow_stop()
    workspace, project = context

    prompt = " ".join(strip_reminders(turn["prompt"]).split())
    summary = payload.get("last_assistant_message") or turn["assistant"]
    if not isinstance(summary, str):
        summary = ""
    # "Waiting on the review" is not memory; the turn that finishes the work is.
    if is_progress_reply(summary):
        return _allow_stop()
    # A typed prompt names the task; a wrapper (session message, task notice,
    # continued session) or a bare answer ("yes, go ahead") does not, so the
    # reply's opening sentence does instead.
    title = prompt
    if not prompt or is_wrapper_prompt(prompt) or is_answer_prompt(prompt):
        title = reply_title(summary) or prompt
    edited = turn["edited_files"]
    if antigravity:
        actions = "Auto-captured from Antigravity Stop event."
        tags = "antigravity,auto-log"
        fallback_title = f"Antigravity session in {project}"
    else:
        actions = "Auto-captured from Claude Code Stop event."
        tags = "claude,auto-log"
        fallback_title = f"Claude Code session in {project}"
    if edited:
        actions += " Files changed: " + ", ".join(edited[:12])
        if len(edited) > 12:
            actions += f" (+{len(edited) - 12} more)"

    result = record_run(
        workspace, project,
        title=title or fallback_title,
        prompt=prompt or "No user prompt captured.",
        summary=truncate(summary, 1500) or "No assistant summary captured.",
        actions=actions,
        tags=tags,
        session=session_id,
    )
    if result.returncode == 0:
        mark_turn_logged(session_id, start_id)
        print("[obsidian-memory] Logged run note to Obsidian.", file=sys.stderr)
    else:
        print(f"[obsidian-memory] record-run failed (non-blocking): {result.stderr[:200]}", file=sys.stderr)
    return _allow_stop()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a memory hook must never break or block the session
        sys.exit(0)
