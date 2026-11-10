#!/usr/bin/env python3
"""Claude Code PostToolUse hook: sync MEMORY file writes to Obsidian.

Fires after Write or Edit tool calls. Only Claude Code's own auto-memory
files (~/.claude/projects/<project>/memory/*.md) are mirrored; other paths
that merely contain "memory" are ignored.

Requires: obmem CLI installed via pipx, and obsidian_hook_common.py next to this file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).parent))
from obsidian_hook_common import active_context, read_payload, record_run  # noqa: E402


def _is_memory_path(file_path: str) -> bool:
    """True for Claude Code auto-memory files: ~/.claude/projects/*/memory/*.md."""
    parts = Path(file_path).expanduser().parts
    if not file_path.lower().endswith(".md") or len(parts) < 4:
        return False
    for index in range(len(parts) - 3):
        if parts[index] == ".claude" and parts[index + 1] == "projects" and "memory" in parts[index + 3:-1]:
            return True
    return False


_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)(#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")


def _slugify(value: str) -> str:
    """Same rule obmem uses for note file names."""
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", value).strip("-")


def _project_dir(workspace: str, project: str) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["obmem", "show-vault", "--workspace", workspace],
            text=True, capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    vault = result.stdout.strip().splitlines()[-1:] if result.returncode == 0 else []
    if not vault:
        return None
    folder = Path(vault[0]) / "Project Memory" / _slugify(project)
    return folder if folder.is_dir() else None


def _mirror_stem(project_dir: Optional[Path], memory_name: str) -> Optional[str]:
    """Newest vault note that mirrors the memory file `memory_name`, if any."""
    if project_dir is None:
        return None
    slug = _slugify(memory_name)
    if not slug:
        return None
    matches = sorted(
        (note.stem for note in project_dir.rglob(f"*-memory-sync-{slug}-md*.md")),
        reverse=True,
    )
    return matches[0] if matches else None


def rewrite_memory_links(text: str, project_dir: Optional[Path]) -> str:
    """Point `[[memory-name]]` links at the vault note that mirrors that memory.

    Claude memory files link to each other by bare memory name. Copied into the
    vault unchanged, those links resolve to nothing (and the note's summary is
    repeated into Run Log and MOC, so each one breaks several times). A link to
    a memory already in the vault becomes `[[<its note>|name]]`; a link to one
    that is not there yet becomes plain text so no broken link is written.
    Path-style links (containing "/") are vault links already and stay as they are.
    """

    def replace(match: "re.Match[str]") -> str:
        target, heading, alias = match.group(1).strip(), match.group(2) or "", match.group(3)
        if "/" in target:
            return match.group(0)
        name = target[:-3] if target.lower().endswith(".md") else target
        label = (alias or name).strip()
        stem = _mirror_stem(project_dir, name)
        if stem is None:
            return label
        return f"[[{stem}{heading}|{label}]]"

    return _WIKILINK_RE.sub(replace, text)


def main() -> int:
    payload = read_payload(sys.stdin.read())
    if payload is None:
        return 0

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return 0

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return 0
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path or not _is_memory_path(file_path):
        return 0

    context = active_context(payload)
    if context is None:
        return 0
    workspace, project = context

    # Read the actual file content from disk (post-write state)
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    if not content.strip():
        return 0

    memory_filename = Path(file_path).name
    content = rewrite_memory_links(content, _project_dir(workspace, project))
    result = record_run(
        workspace, project,
        title=f"Memory sync: {memory_filename} ({project})",
        prompt=f"Auto-memory file written: {file_path}",
        summary=content,
        actions=f"Claude wrote to {memory_filename}. Content synced to Obsidian vault.",
        tags="claude,auto-log,memory-sync",
    )
    if result.returncode == 0:
        print(f"[obsidian-memory] Synced {memory_filename} to Obsidian vault.", file=sys.stderr)
    else:
        print(
            f"[obsidian-memory] memory-sync record-run failed (non-blocking): {result.stderr[:200]}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
