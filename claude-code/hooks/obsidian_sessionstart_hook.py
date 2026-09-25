#!/usr/bin/env python3
"""Claude Code SessionStart hook: validate Obsidian memory bank connectivity.

Runs obmem doctor at the start of each session to catch issues early
(Obsidian not running, vault unmapped, CLI missing) instead of silently
failing on every subsequent hook invocation.
Output goes to stdout so Claude sees it as hook context.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import active_context, read_payload  # noqa: E402


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
