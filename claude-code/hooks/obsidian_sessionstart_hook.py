#!/usr/bin/env python3
"""Claude Code SessionStart hook: validate Obsidian memory bank connectivity.

Runs obmem doctor at the start of each session to catch issues early
(Obsidian not running, vault unmapped, CLI missing) instead of silently
failing on every subsequent hook invocation.

Output goes to stdout so Claude sees it as hook context.
Requires: obmem CLI installed via pipx.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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

    # Check if vault is mapped — if not, skip silently (user hasn't set up this project)
    check = subprocess.run(
        ["obmem", "show-vault", "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        return 0

    # Run doctor to validate full stack
    result = subprocess.run(
        ["obmem", "doctor", "--workspace", workspace],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode == 0:
        print(f"[obsidian-memory] Vault healthy for {project_name}.")
    else:
        # Surface the issue so Claude knows memory hooks may be degraded
        stderr_snippet = result.stderr.strip()[:300] if result.stderr else ""
        stdout_snippet = result.stdout.strip()[:300] if result.stdout else ""
        detail = stderr_snippet or stdout_snippet or "unknown error"
        print(
            f"[obsidian-memory] WARNING: Obsidian vault health check failed for "
            f"{project_name}. Memory hooks may not work this session. "
            f"Detail: {detail}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
