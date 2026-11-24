#!/usr/bin/env python3
"""Antigravity plugin hook launcher for Obsidian CLI Memory Bank.

Dispatches Antigravity lifecycle hooks (`SessionStart`, `PreInvocation`, `Stop`)
to the shared hook implementations without duplicating code.

Resolution order for hook scripts:
1. Bundled alongside this file (`antigravity/hooks/` when installed via `--copy`)
2. Repository checkout (`../../claude-code/hooks/` when symlinked or run in-repo)
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

_HOOK_FILES = {
    "sessionstart": "obsidian_sessionstart_hook.py",
    "preprompt": "obsidian_preprompt_hook.py",
    "poststop": "obsidian_poststop_hook.py",
}


def _fallback_output(hook_name: str) -> str:
    if hook_name == "poststop":
        return json.dumps({"decision": "allow"})
    return "{}"


def _resolve_hook_script(hook_name: str) -> Path | None:
    filename = _HOOK_FILES.get(hook_name)
    if not filename:
        return None
    here = Path(__file__).resolve().parent
    candidates = [
        here / filename,
        here.parents[1] / "claude-code" / "hooks" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    hook_name = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    script = _resolve_hook_script(hook_name)
    if script is None:
        print(_fallback_output(hook_name))
        return 0
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *sys.argv[2:]]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return code
    except Exception:
        print(_fallback_output(hook_name))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
