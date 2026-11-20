#!/usr/bin/env python3
"""Claude Code PreCompact hook: note that this session is about to compact.

From here on, notes this session wrote earlier are no longer in its context,
so the prompt hook may bring them back. The PreCompact payload carries no
summary; the SessionStart hook saves the summary Claude Code writes, once the
compaction is done (it used to be a thin list of recent prompts saved here).

Requires: obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import claim_summary, compact_summary, mark_compacted, read_payload  # noqa: E402


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0
    session_id = str(payload.get("session_id") or "")
    mark_compacted(session_id)
    # The summary on disk now is the previous compaction's: claim it so the
    # SessionStart hook waits for the new one instead of saving this again.
    path = payload.get("transcript_path")
    if isinstance(path, str):
        claim_summary(session_id, compact_summary(path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a memory hook must never break or block the session
        sys.exit(0)
