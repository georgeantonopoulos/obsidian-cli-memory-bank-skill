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
from obsidian_hook_common import (  # noqa: E402
    active_context, read_payload, record_run, redact_secrets, truncate,
)


def _is_memory_path(file_path: str) -> bool:
    """True for Claude Code auto-memory files: ~/.claude/projects/*/memory/*.md."""
    parts = Path(file_path).expanduser().parts
    if not file_path.lower().endswith(".md") or len(parts) < 4:
        return False
    for index in range(len(parts) - 3):
        if parts[index] == ".claude" and parts[index + 1] == "projects" and "memory" in parts[index + 3:-1]:
            return True
    return False


_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]|#]+)(#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
# Fenced blocks and inline code are left exactly as written.
_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]+`", re.DOTALL)
_RUN_STAMP = r"\d{4}-\d{2}-\d{2}-\d{4}-"
SUMMARY_LIMIT = 3000


def _slugify(value: str) -> str:
    """Same rule obmem uses for note file names."""
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", value).strip("-")


def sync_title(memory_filename: str, project: str) -> str:
    return f"Memory sync: {memory_filename} ({project})"


def _mirror_slug(memory_filename: str, project: str) -> str:
    """The slug record_run gives a mirror note: built from the same title, cut the same way."""
    return _slugify(truncate(redact_secrets(sync_title(memory_filename, project)), 80))


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


class _VaultIndex:
    """Run-note stems of one project, plus every note stem in the vault, read once."""

    def __init__(self, project_dir: Optional[Path]):
        self.project_dir = project_dir
        self._mirrors: Optional[dict] = None
        self._stems: Optional[set] = None

    def mirror(self, slug: str) -> Optional[str]:
        if self.project_dir is None:
            return None
        if self._mirrors is None:
            self._mirrors = {}
            stamp = re.compile(_RUN_STAMP)
            for note in self.project_dir.rglob("*-memory-sync-*.md"):
                if stamp.match(note.stem):
                    key = note.stem[16:]
                    if note.stem > self._mirrors.get(key, ""):
                        self._mirrors[key] = note.stem
        return self._mirrors.get(slug)

    def has_note(self, stem: str) -> bool:
        if self.project_dir is None:
            return False
        if self._stems is None:
            vault = self.project_dir.parent.parent
            self._stems = {note.stem for note in vault.rglob("*.md")}
        return stem in self._stems


def rewrite_memory_links(text: str, project_dir: Optional[Path], project: str = "") -> str:
    """Point `[[memory-name]]` links at the vault note that mirrors that memory.

    Claude memory files link to each other by bare memory name. Copied into the
    vault unchanged, those links resolve to nothing (and the note's summary is
    repeated into Run Log and MOC, so each one breaks several times).
      - a memory already mirrored in the vault becomes `[[<its note>|name]]`;
      - a name that already resolves in the vault (a note with that name) stays;
      - anything else becomes plain text, so no broken link is written.
    Path links (with "/"), embeds (`![[...]]`) and code are left as written.
    """
    index = _VaultIndex(project_dir)

    def replace(match: "re.Match[str]") -> str:
        target, heading, alias = match.group(1).strip(), match.group(2) or "", match.group(3)
        if "/" in target:
            return match.group(0)
        name = target[:-3] if target.lower().endswith(".md") else target
        label = (alias or name).strip()
        stem = index.mirror(_mirror_slug(f"{name}.md", project))
        if stem is not None:
            return f"[[{stem}{heading}|{label}]]"
        if index.has_note(name):
            return match.group(0)
        return label

    pieces: list = []
    last = 0
    for code in _CODE_RE.finditer(text):
        pieces.append(_WIKILINK_RE.sub(replace, text[last:code.start()]))
        pieces.append(code.group(0))
        last = code.end()
    pieces.append(_WIKILINK_RE.sub(replace, text[last:]))
    return "".join(pieces)


def _description(header: str) -> str:
    """`description:` from YAML frontmatter, including folded (`>`) and literal
    (`|`) values that continue on indented lines."""
    lines = header.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value[:1] in (">", "|"):
            block = []
            for follow in lines[index + 1:]:
                if follow.strip() and not follow[:1].isspace():
                    break
                block.append(follow.strip())
            return " ".join(part for part in block if part)
        return value.strip('"\'')
    return ""


def without_frontmatter(text: str) -> str:
    """Memory body, led by its `description:` so the first sentence (which goes
    into the vault's index lines) says what the memory is."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    header, body = text[3:end], text[end + 4:].strip()
    description = _description(header)
    if description and not description.endswith((".", "!", "?")):
        description += "."
    return f"{description}\n\n{body}".strip() if description else body


def fit_summary(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """Cut to the summary limit without leaving half a `[[link`."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    if cut.rfind("[[") > cut.rfind("]]"):
        cut = cut[: cut.rfind("[[")]
    return cut.rstrip() + "..."


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
    try:
        content = rewrite_memory_links(content, _project_dir(workspace, project), project)
    except Exception:  # never lose the sync over a link rewrite
        pass
    # Redact before cutting: a cut key is too short for redact_secrets to spot.
    content = fit_summary(redact_secrets(without_frontmatter(content)))
    result = record_run(
        workspace, project,
        title=sync_title(memory_filename, project),
        prompt=f"Auto-memory file written: {file_path}",
        summary=content,
        actions=f"Claude wrote to {memory_filename}. Content synced to Obsidian vault.",
        tags="claude,auto-log,memory-sync",
        session=str(payload.get("session_id") or ""),
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
