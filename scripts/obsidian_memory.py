#!/usr/bin/env python3
"""
Manage a project knowledge memory bank in Obsidian via Obsidian CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


SKILL_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = SKILL_ROOT / "state"
STATE_FILE = STATE_DIR / "vault_config.json"
USER_STATE_FILE = Path.home() / ".local" / "state" / "obsidian-cli-memory-bank" / "vault_config.json"
PROJECT_ROOT = "Project Memory"
PROJECTS_INDEX_PATH = Path(PROJECT_ROOT) / "Projects Index.md"
DEFAULT_AUDIT_EVERY_RUNS = 5
COMPACTION_NOTE_LIMIT = 14
COMPACTION_SOURCE_LIMIT = 80
STOP_WORDS = {
    "about",
    "above",
    "after",
    "again",
    "agent",
    "also",
    "and",
    "another",
    "around",
    "asked",
    "because",
    "before",
    "between",
    "but",
    "can",
    "check",
    "code",
    "codex",
    "command",
    "current",
    "done",
    "each",
    "file",
    "files",
    "fix",
    "fixed",
    "for",
    "from",
    "had",
    "has",
    "have",
    "into",
    "just",
    "local",
    "make",
    "memory",
    "more",
    "next",
    "note",
    "notes",
    "now",
    "out",
    "path",
    "project",
    "prompt",
    "record",
    "recorded",
    "repo",
    "run",
    "runs",
    "source",
    "same",
    "should",
    "that",
    "the",
    "then",
    "this",
    "through",
    "updated",
    "use",
    "user",
    "using",
    "vault",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "work",
    "working",
    "hyperprompt",
    "learnings",
    "medium",
    "simple",
    "single",
    "multi",
    "wide",
    "tool",
    "claude",
    "auto",
    "log",
    "summary",
    "insight",
}
GOTCHA_WORDS = {
    "access",
    "blocked",
    "broken",
    "bug",
    "cannot",
    "crash",
    "duplicate",
    "error",
    "fail",
    "failed",
    "fails",
    "fallback",
    "gotcha",
    "missing",
    "not",
    "permission",
    "permissions",
    "regression",
    "risk",
    "unsupported",
    "verify",
    "warning",
    "wrong",
}
TOPIC_RULES: List[Tuple[str, str]] = [
    ("arri", r"\b(arri|arriraw|arricore|alexa|ari|hde|logc4?)\b"),
    ("braw", r"\b(braw|blackmagic)\b"),
    ("color-management", r"\b(color|aces|acescg|ap0|ap1|ocio|openexr|exr|saturation|chromaticities|logc3|srgb|p3)\b"),
    ("export", r"\b(export|exports|exporter|conversion|transcode|transcoder)\b"),
    ("permissions", r"\b(permission|permissions|access|grant access|sandbox)\b"),
    ("mxf", r"\b(mxf|dnxhd|vc3)\b"),
    ("video-export", r"\b(h264|h\.264|prores|mov|mp4|avassetwriter|avfoundation|videotranscoder)\b"),
    ("audio", r"\b(audio|pcm|channel|sample)\b"),
    ("duration", r"\b(duration|fps|framerate|frame-rate|framecount|frame-count|retiming)\b"),
    ("queue", r"\b(queue|queued|batch)\b"),
    ("release", r"\b(beta|testflight|release|ship|build|archive|version)\b"),
    ("testing", r"\b(test|tests|xcode|regression|fixture|verify|verified|validation|runtime|launch)\b"),
    ("performance", r"\b(performance|slow|speed|faster|cache|memory|balloon|optimi[sz]e|benchmark)\b"),
    ("debugging", r"\b(crash|bug|postmortem|warning|failure|failed|fails|error|root cause|lessons)\b"),
    ("git", r"\b(git|commit|push|branch|pr|pull request|merge|main)\b"),
    ("docs-research", r"\b(docs|documentation|research|plan|spec|guide|investigate|investigation)\b"),
    ("tooling", r"\b(computer use|plugin|mcp|hook|notify|claude|codex|obsidian|memory sync)\b"),
    ("ui", r"\b(ui|sidebar|selection|panel|view|button|layout|scroll)\b"),
]


def slugify(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def sanitize_note_title_component(value: str, fallback: str = "Project") -> str:
    # Keep note titles readable while blocking path traversal/separator injection.
    sanitized = value.strip()
    sanitized = sanitized.replace("/", " ").replace("\\", " ")
    sanitized = sanitized.replace("..", " ")
    sanitized = re.sub(r"[:*?\"<>|]+", " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or fallback


def normalize_workspace(path: Path) -> str:
    return str(path.resolve())


class ConfigStore:
    def __init__(self, state_file: Optional[Path] = None) -> None:
        if state_file is None:
            env_state = os.environ.get("OBMEM_STATE_FILE")
            state_file = Path(env_state).expanduser() if env_state else STATE_FILE
        if state_file == STATE_FILE and USER_STATE_FILE.exists():
            state_file = USER_STATE_FILE
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            self._harden_permissions()

    def load(self) -> Dict[str, object]:
        if not self.state_file.exists():
            return {
                "default_vault_path": "",
                "workspace_vaults": {},
                "audit_every_runs": DEFAULT_AUDIT_EVERY_RUNS,
                "run_counters": {},
            }
        with self.state_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "workspace_vaults" not in data or not isinstance(data["workspace_vaults"], dict):
            data["workspace_vaults"] = {}
        if "default_vault_path" not in data:
            data["default_vault_path"] = ""
        if "audit_every_runs" not in data or not isinstance(data["audit_every_runs"], int):
            data["audit_every_runs"] = DEFAULT_AUDIT_EVERY_RUNS
        if "run_counters" not in data or not isinstance(data["run_counters"], dict):
            data["run_counters"] = {}
        return data

    def save(self, data: Dict[str, object]) -> None:
        try:
            self._write_state(data)
        except PermissionError:
            if self.state_file != STATE_FILE:
                raise
            self.state_file = USER_STATE_FILE
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self._write_state(data)

    def _write_state(self, data: Dict[str, object]) -> None:
        with self.state_file.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        self._harden_permissions()

    def set_vault(self, vault_path: Path, workspace: Optional[Path]) -> Dict[str, object]:
        data = self.load()
        normalized_vault = str(vault_path.resolve())
        if workspace is not None:
            key = normalize_workspace(workspace)
            data["workspace_vaults"][key] = normalized_vault  # type: ignore[index]
        if not data.get("default_vault_path"):
            data["default_vault_path"] = normalized_vault
        self.save(data)
        return data

    def resolve_vault(self, workspace: Optional[Path]) -> str:
        data = self.load()
        workspace_map: Dict[str, str] = data.get("workspace_vaults", {})  # type: ignore[assignment]
        if workspace is not None:
            current = workspace.resolve()
            # Support nested directories by checking nearest ancestor first.
            for candidate in [current, *current.parents]:
                key = str(candidate)
                if key in workspace_map:
                    return workspace_map[key]
        return str(data.get("default_vault_path", ""))

    def get_audit_every_runs(self) -> int:
        data = self.load()
        value = data.get("audit_every_runs", DEFAULT_AUDIT_EVERY_RUNS)
        if not isinstance(value, int):
            return DEFAULT_AUDIT_EVERY_RUNS
        return max(0, value)

    def set_audit_every_runs(self, runs: int) -> None:
        data = self.load()
        data["audit_every_runs"] = max(0, runs)
        self.save(data)

    def bump_run_counter(self, workspace: Path, project_slug: str) -> int:
        data = self.load()
        counters: Dict[str, int] = data.get("run_counters", {})  # type: ignore[assignment]
        key = self._counter_key(workspace, project_slug)
        next_value = int(counters.get(key, 0)) + 1
        counters[key] = next_value
        data["run_counters"] = counters
        self.save(data)
        return next_value

    def reset_run_counter(self, workspace: Path, project_slug: str) -> None:
        data = self.load()
        counters: Dict[str, int] = data.get("run_counters", {})  # type: ignore[assignment]
        key = self._counter_key(workspace, project_slug)
        if key in counters:
            del counters[key]
            data["run_counters"] = counters
            self.save(data)

    @staticmethod
    def _counter_key(workspace: Path, project_slug: str) -> str:
        return f"{normalize_workspace(workspace)}::{project_slug}"

    def _harden_permissions(self) -> None:
        try:
            self.state_file.chmod(0o600)
        except OSError:
            # Best-effort on filesystems that may not support chmod semantics.
            pass


@dataclass
class NotePaths:
    project_slug: str
    project_dir: Path
    home: Path
    moc: Path
    run_log: Path
    decisions: Path
    questions: Path
    architecture: Path
    roadmap: Path
    debugging_notes: Path
    release_notes: Path
    current_memory: Path
    topics_dir: Path
    compactions_dir: Path
    archived_runs_dir: Path
    archived_topics_dir: Path
    runs_dir: Path


def build_note_paths(project_name: str) -> NotePaths:
    project_slug = slugify(project_name) or "project"
    project_dir = Path(PROJECT_ROOT) / project_slug
    project_display_name = sanitize_note_title_component(project_name, fallback="Project")
    project_home_name = f"{project_display_name} Home".strip()
    if project_home_name == "Home":
        project_home_name = "Project Home"
    home = project_dir / f"{project_home_name}.md"
    moc = project_dir / "MOC.md"
    run_log = project_dir / "Run Log.md"
    decisions = project_dir / "Decisions.md"
    questions = project_dir / "Open Questions.md"
    architecture = project_dir / "Architecture.md"
    roadmap = project_dir / "Roadmap.md"
    debugging_notes = project_dir / "Debugging Notes.md"
    release_notes = project_dir / "Release Notes.md"
    current_memory = project_dir / "Current Memory.md"
    topics_dir = project_dir / "Topics"
    compactions_dir = project_dir / "Compactions"
    archived_runs_dir = project_dir / "Archive" / "Runs"
    archived_topics_dir = project_dir / "Archive" / "Topics"
    runs_dir = project_dir / "Runs"
    return NotePaths(
        project_slug=project_slug,
        project_dir=project_dir,
        home=home,
        moc=moc,
        run_log=run_log,
        decisions=decisions,
        questions=questions,
        architecture=architecture,
        roadmap=roadmap,
        debugging_notes=debugging_notes,
        release_notes=release_notes,
        current_memory=current_memory,
        topics_dir=topics_dir,
        compactions_dir=compactions_dir,
        archived_runs_dir=archived_runs_dir,
        archived_topics_dir=archived_topics_dir,
        runs_dir=runs_dir,
    )


class ObsidianCLI:
    def __init__(self, vault_path: Path, dry_run: bool = False) -> None:
        self.vault_path = vault_path
        self.dry_run = dry_run

    def run(self, command: str, *args: str, retries: int = 2) -> str:
        local_result = self.run_local(command, *args)
        if local_result is not None:
            return local_result

        cmd = ["obsidian", command, *args]
        if self.dry_run:
            printable = " ".join(cmd)
            return f"[dry-run] {printable}"
        last_error: RuntimeError | None = None
        for attempt in range(1 + retries):
            completed = subprocess.run(
                cmd,
                cwd=self.vault_path,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode == 0 and not _contains_cli_error(
                completed.stdout
            ) and not _contains_cli_error(completed.stderr):
                return completed.stdout.strip()
            last_error = RuntimeError(
                f"Obsidian CLI failed ({completed.returncode}) for: {' '.join(cmd)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
            if _is_transient_ipc_error(completed) and attempt < retries:
                time.sleep(1)
                continue
            break
        raise last_error  # type: ignore[misc]

    def run_local(self, command: str, *args: str) -> Optional[str]:
        if command == "create":
            relative_path = _arg_value(args, "path")
            content = _arg_value(args, "content") or ""
            if not relative_path:
                return None
            return self.write_file(Path(relative_path), content, overwrite=False)
        if command == "append":
            relative_path = _arg_value(args, "path")
            content = _arg_value(args, "content") or ""
            if not relative_path:
                return None
            return self.append_file(Path(relative_path), content)
        if command == "read":
            relative_path = _arg_value(args, "path")
            if not relative_path:
                return None
            return self.read_file(Path(relative_path))
        if command == "search":
            query = _arg_value(args, "query") or " ".join(args)
            return self.search_files(query)
        if command == "unresolved":
            return self.audit_unresolved(verbose="verbose" in args)
        if command == "orphans":
            return self.audit_orphans()
        if command == "deadends":
            return self.audit_deadends()
        if command == "backlinks":
            relative_path = _arg_value(args, "path")
            if not relative_path:
                return None
            return self.audit_backlinks(Path(relative_path), counts_only="counts" in args)
        return None

    def write_file(self, relative_path: Path, content: str, *, overwrite: bool) -> str:
        absolute = self.vault_path / relative_path
        if self.dry_run:
            return f"[dry-run] write {relative_path.as_posix()}"
        if absolute.exists() and not overwrite:
            return f"exists:{relative_path.as_posix()}"
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_text(content, encoding="utf-8")
        return f"created:{relative_path.as_posix()}"

    def append_file(self, relative_path: Path, content: str) -> str:
        absolute = self.vault_path / relative_path
        if self.dry_run:
            return f"[dry-run] append {relative_path.as_posix()}"
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with absolute.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return f"appended:{relative_path.as_posix()}"

    def read_file(self, relative_path: Path) -> str:
        absolute = self.vault_path / relative_path
        if self.dry_run:
            return f"[dry-run] read {relative_path.as_posix()}"
        if not absolute.exists():
            raise RuntimeError(f"Note not found: {relative_path.as_posix()}")
        return absolute.read_text(encoding="utf-8")

    def search_files(self, query: str) -> str:
        scoped_path, terms = _parse_local_search_query(query)
        root = self.vault_path / scoped_path if scoped_path else self.vault_path
        if self.dry_run:
            return f"[dry-run] search {query}"
        if not root.exists():
            return "Found 0 hits."

        hits: List[Tuple[int, int, str]] = []
        for note in root.rglob("*.md"):
            try:
                text = note.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            haystack = f"{note.stem}\n{text}".lower()
            score = sum(haystack.count(term.lower()) for term in terms)
            if not terms or score > 0:
                relative = note.relative_to(self.vault_path).as_posix()
                hits.append((score, _search_priority(relative), relative))

        hits.sort(key=lambda item: (-item[1], -item[0], item[2]))
        lines = [f"Found {len(hits)} hits."]
        lines.extend(f"  {path} (score {score})" for score, _priority, path in hits[:25])
        return "\n".join(lines)

    def audit_unresolved(self, *, verbose: bool) -> str:
        existing_stems = {note.stem for note in self.vault_path.rglob("*.md")}
        counts: Dict[str, int] = {}
        sources: Dict[str, List[str]] = {}
        for note in self.vault_path.rglob("*.md"):
            body = note.read_text(encoding="utf-8")
            for target in _extract_wikilinks(body):
                if target in existing_stems:
                    continue
                counts[target] = counts.get(target, 0) + 1
                sources.setdefault(target, []).append(note.relative_to(self.vault_path).as_posix())

        if not counts:
            return "0 unresolved link target(s)."
        lines = [f"{len(counts)} unresolved link target(s)."]
        for target, count in sorted(counts.items()):
            lines.append(f"- [[{target}]]: {count}")
            if verbose:
                for source in sources.get(target, [])[:5]:
                    lines.append(f"  - {source}")
        return "\n".join(lines)

    def audit_orphans(self) -> str:
        notes = list(self.vault_path.rglob("*.md"))
        linked = _linked_note_stems(notes)
        orphans = [note for note in notes if note.stem not in linked]
        if not orphans:
            return "0 orphan note(s)."
        lines = [f"{len(orphans)} orphan note(s)."]
        lines.extend(f"- {note.relative_to(self.vault_path).as_posix()}" for note in orphans)
        return "\n".join(lines)

    def audit_deadends(self) -> str:
        deadends: List[Path] = []
        for note in self.vault_path.rglob("*.md"):
            if not _extract_wikilinks(note.read_text(encoding="utf-8")):
                deadends.append(note)
        if not deadends:
            return "0 dead-end note(s)."
        lines = [f"{len(deadends)} dead-end note(s)."]
        lines.extend(f"- {note.relative_to(self.vault_path).as_posix()}" for note in deadends)
        return "\n".join(lines)

    def audit_backlinks(self, relative_path: Path, *, counts_only: bool) -> str:
        target = (self.vault_path / relative_path).stem
        backlinks: List[str] = []
        for note in self.vault_path.rglob("*.md"):
            if note.relative_to(self.vault_path) == relative_path:
                continue
            if target in _extract_wikilinks(note.read_text(encoding="utf-8")):
                backlinks.append(note.relative_to(self.vault_path).as_posix())
        if counts_only:
            return f"{len(backlinks)} backlink(s) to [[{target}]]."
        lines = [f"{len(backlinks)} backlink(s) to [[{target}]]."]
        lines.extend(f"- {path}" for path in backlinks)
        return "\n".join(lines)

    def ensure_note(self, relative_path: Path, content: str) -> str:
        absolute = self.vault_path / relative_path
        if absolute.exists():
            return f"exists:{relative_path.as_posix()}"
        try:
            return self.run(
                "create",
                f"path={relative_path.as_posix()}",
                f"content={content}",
                "silent",
            )
        except RuntimeError:
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(content, encoding="utf-8")
            return f"created (direct write):{relative_path.as_posix()}"

    def append(self, relative_path: Path, content: str) -> str:
        return self.run(
            "append",
            f"path={relative_path.as_posix()}",
            f"content={content}",
        )

    def read(self, relative_path: Path) -> str:
        return self.run("read", f"path={relative_path.as_posix()}")


def escape_yaml(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f"\"{escaped}\""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_frontmatter(
    *,
    note_type: str,
    project: str,
    tags: List[str],
    extra: Optional[Dict[str, str]] = None,
) -> str:
    lines = [
        "---",
        f"type: {escape_yaml(note_type)}",
        f"project: {escape_yaml(project)}",
        f"created: {escape_yaml(now_iso())}",
        f"updated: {escape_yaml(now_iso())}",
    ]
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {escape_yaml(tag)}")
    if extra:
        for key, value in extra.items():
            lines.append(f"{key}: {escape_yaml(value)}")
    lines.append("---")
    return "\n".join(lines)


def build_seed_notes(project_name: str, paths: NotePaths) -> Dict[Path, str]:
    project_home_title = paths.home.stem
    frontmatter_home = build_frontmatter(
        note_type="project-home",
        project=project_name,
        tags=["project-home", paths.project_slug],
    )
    home = "\n".join(
        [
            frontmatter_home,
            "",
            f"# {project_home_title}",
            "",
            f"Primary hub for [[{paths.moc.stem}]], [[{paths.run_log.stem}]], [[{paths.decisions.stem}]], and [[{paths.questions.stem}]].",
            "",
            "## Active Focus",
            "- [ ] Add first execution summary",
            "",
            "## Knowledge Map",
            f"- [[{paths.current_memory.stem}]]",
            f"- [[{paths.moc.stem}]]",
            f"- [[{paths.decisions.stem}]]",
            f"- [[{paths.questions.stem}]]",
            f"- [[{paths.run_log.stem}]]",
            f"- [[{paths.architecture.stem}]]",
            f"- [[{paths.roadmap.stem}]]",
            f"- [[{paths.debugging_notes.stem}]]",
            f"- [[{paths.release_notes.stem}]]",
            "",
            "## Retrieval Cues",
            "- Add stable keywords for high-value searches.",
        ]
    )

    moc = "\n".join(
        [
            build_frontmatter(
                note_type="moc",
                project=project_name,
                tags=["moc", paths.project_slug],
            ),
            "",
            f"# {paths.moc.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            "",
            "## Core Topics",
            f"- [[{paths.current_memory.stem}]]",
            "- [[Architecture]]",
            "- [[Roadmap]]",
            "- [[Debugging Notes]]",
            "- [[Release Notes]]",
            "",
            "## Working Sets",
            f"- [[{paths.decisions.stem}]]",
            f"- [[{paths.questions.stem}]]",
            f"- [[{paths.run_log.stem}]]",
            "",
            "## Recent Runs",
            "- Add the latest execution notes here for quick traversal.",
        ]
    )

    run_log = "\n".join(
        [
            build_frontmatter(
                note_type="run-log",
                project=project_name,
                tags=["runs", paths.project_slug],
            ),
            "",
            f"# {paths.run_log.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            "",
            "## Entries",
            "- Add run notes with timestamp and key outcomes.",
        ]
    )

    decisions = "\n".join(
        [
            build_frontmatter(
                note_type="decisions",
                project=project_name,
                tags=["decisions", paths.project_slug],
            ),
            "",
            f"# {paths.decisions.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            "",
            "## Decision Register",
            "- Record irreversible or expensive choices and rationale.",
        ]
    )

    questions = "\n".join(
        [
            build_frontmatter(
                note_type="open-questions",
                project=project_name,
                tags=["questions", paths.project_slug],
            ),
            "",
            f"# {paths.questions.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            "",
            "## Open Questions",
            "- Track unknowns that block confident execution.",
        ]
    )

    architecture = "\n".join(
        [
            build_frontmatter(
                note_type="architecture",
                project=project_name,
                tags=["architecture", paths.project_slug],
            ),
            "",
            f"# {paths.architecture.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            f"MOC: [[{paths.moc.stem}]]",
            "",
            "## Current Shape",
            "- Capture the key systems, boundaries, and integration points.",
            "",
            "## Linked Context",
            f"- [[{paths.roadmap.stem}]]",
            f"- [[{paths.debugging_notes.stem}]]",
            f"- [[{paths.release_notes.stem}]]",
        ]
    )

    roadmap = "\n".join(
        [
            build_frontmatter(
                note_type="roadmap",
                project=project_name,
                tags=["roadmap", paths.project_slug],
            ),
            "",
            f"# {paths.roadmap.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            f"MOC: [[{paths.moc.stem}]]",
            "",
            "## Current Priorities",
            "- Track near-term milestones and larger follow-up work.",
            "",
            "## Linked Context",
            f"- [[{paths.architecture.stem}]]",
            f"- [[{paths.questions.stem}]]",
            f"- [[{paths.release_notes.stem}]]",
        ]
    )

    debugging_notes = "\n".join(
        [
            build_frontmatter(
                note_type="debugging-notes",
                project=project_name,
                tags=["debugging", paths.project_slug],
            ),
            "",
            f"# {paths.debugging_notes.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            f"MOC: [[{paths.moc.stem}]]",
            "",
            "## Current Investigations",
            "- Capture active failures, root-cause notes, and reproduction details.",
            "",
            "## Linked Context",
            f"- [[{paths.architecture.stem}]]",
            f"- [[{paths.questions.stem}]]",
            f"- [[{paths.run_log.stem}]]",
        ]
    )

    release_notes = "\n".join(
        [
            build_frontmatter(
                note_type="release-notes",
                project=project_name,
                tags=["release-notes", paths.project_slug],
            ),
            "",
            f"# {paths.release_notes.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            f"MOC: [[{paths.moc.stem}]]",
            "",
            "## Shipped Changes",
            "- Summarize notable releases, migrations, and rollout concerns.",
            "",
            "## Linked Context",
            f"- [[{paths.roadmap.stem}]]",
            f"- [[{paths.architecture.stem}]]",
            f"- [[{paths.run_log.stem}]]",
        ]
    )

    current_memory = "\n".join(
        [
            build_frontmatter(
                note_type="current-memory",
                project=project_name,
                tags=["current-memory", "compacted", paths.project_slug],
            ),
            "",
            f"# {paths.current_memory.stem}",
            "",
            f"Parent note: [[{project_home_title}]]",
            f"MOC: [[{paths.moc.stem}]]",
            "",
            "## High-Signal Memory",
            "- Run `obmem compact-project --project \"PROJECT\"` to distill run logs here.",
            "",
            "## Topic Index",
            "- Topic notes will appear under `Topics/` after compaction.",
            "",
            "## Latest Compaction",
            "- None yet.",
        ]
    )

    return {
        paths.home: home,
        paths.moc: moc,
        paths.run_log: run_log,
        paths.decisions: decisions,
        paths.questions: questions,
        paths.architecture: architecture,
        paths.roadmap: roadmap,
        paths.debugging_notes: debugging_notes,
        paths.release_notes: release_notes,
        paths.current_memory: current_memory,
    }


def parse_tags(raw_tags: str) -> List[str]:
    if not raw_tags.strip():
        return []
    tags = [tag.strip() for tag in raw_tags.split(",")]
    return [tag for tag in tags if tag]


def ensure_vault_ready(vault_path: Path) -> None:
    if not vault_path.exists():
        raise SystemExit(f"Vault path does not exist: {vault_path}")
    if not vault_path.is_dir():
        raise SystemExit(f"Vault path is not a directory: {vault_path}")


def _contains_cli_error(text: str) -> bool:
    lowered = text.lower()
    return re.search(r"(^|\n)\s*error[:\s]", lowered) is not None


def _is_transient_ipc_error(result: subprocess.CompletedProcess[str]) -> bool:
    combined = (result.stdout or "") + (result.stderr or "")
    return "unable to connect to main process" in combined.lower()


def _arg_value(args: Tuple[str, ...], key: str) -> Optional[str]:
    prefix = f"{key}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


def _parse_local_search_query(query: str) -> Tuple[Optional[Path], List[str]]:
    path_match = re.search(r'path:"([^"]+)"', query)
    scoped_path = Path(path_match.group(1)) if path_match else None
    without_path = re.sub(r'path:"[^"]+"', " ", query)
    tokens = re.findall(r"[A-Za-z0-9_#.+-]+", without_path)
    ignored = {"or", "and", "not", "path"}
    terms = [token for token in tokens if token.lower() not in ignored]
    return scoped_path, terms


def _search_priority(relative_path: str) -> int:
    """Prefer distilled memory over raw execution logs during retrieval."""
    if relative_path.endswith("/Current Memory.md"):
        return 120
    if "/Archive/" in relative_path:
        return 15
    if "/Topics/" in relative_path:
        return 110
    if "/Compactions/" in relative_path:
        return 95
    if relative_path.endswith(("/Decisions.md", "/Open Questions.md", "/Architecture.md")):
        return 90
    if relative_path.endswith(("/MOC.md", "/Roadmap.md", "/Debugging Notes.md", "/Release Notes.md")):
        return 80
    if "/Runs/" in relative_path:
        return 25
    return 50


def _extract_wikilinks(body: str) -> List[str]:
    links: List[str] = []
    seen = set()
    for raw in re.findall(r"\[\[([^\]]+)\]\]", body):
        target = raw.split("|", maxsplit=1)[0].split("#", maxsplit=1)[0].strip()
        if not target:
            continue
        stem = Path(target).stem
        if stem and stem not in seen:
            seen.add(stem)
            links.append(stem)
    return links


def _linked_note_stems(notes: List[Path]) -> set[str]:
    linked: set[str] = set()
    for note in notes:
        linked.update(_extract_wikilinks(note.read_text(encoding="utf-8")))
    return linked


def ensure_project_dirs(vault_path: Path, paths: NotePaths, dry_run: bool) -> None:
    targets = [
        vault_path / paths.project_dir,
        vault_path / paths.runs_dir,
        vault_path / paths.topics_dir,
        vault_path / paths.compactions_dir,
        vault_path / paths.archived_runs_dir,
        vault_path / paths.archived_topics_dir,
    ]
    for target in targets:
        if dry_run:
            print(f"[dry-run] mkdir -p {target}")
            continue
        target.mkdir(parents=True, exist_ok=True)


def ensure_projects_index(cli: ObsidianCLI, paths: NotePaths) -> None:
    entry = f"- [[{paths.home.stem}]] (`{paths.project_slug}`)"
    index_content = "\n".join(
        [
            build_frontmatter(
                note_type="projects-index",
                project="Global",
                tags=["projects", "index"],
            ),
            "",
            "# Projects Index",
            "",
            "Master index of project homes in this vault.",
            "",
            "## Projects",
            entry,
        ]
    )
    cli.ensure_note(PROJECTS_INDEX_PATH, index_content)
    index_abs = cli.vault_path / PROJECTS_INDEX_PATH
    if not index_abs.exists():
        return
    existing = index_abs.read_text(encoding="utf-8")
    if entry in existing:
        return
    cli.append(PROJECTS_INDEX_PATH, entry)


def bootstrap_project(cli: ObsidianCLI, project: str) -> NotePaths:
    paths = build_note_paths(project)
    ensure_project_dirs(cli.vault_path, paths, cli.dry_run)
    notes = build_seed_notes(project, paths)
    print(f"Bootstrapping project memory in vault: {cli.vault_path}")
    for relative_path, content in notes.items():
        result = cli.ensure_note(relative_path, content)
        print(f"- {relative_path.as_posix()}: {result or 'created'}")
    ensure_projects_index(cli, paths)
    return paths


def resolve_workspace_path(workspace_arg: Optional[str]) -> Path:
    workspace = Path(workspace_arg).expanduser() if workspace_arg else Path.cwd()
    return workspace.resolve()


# ---------------------------------------------------------------------------
# Bidirectional linking helpers
# ---------------------------------------------------------------------------

RELATED_HEADING = "## Related"


def _parse_related_arg(raw: Optional[str]) -> List[str]:
    """Parse a comma/newline-separated list of note references."""
    if not raw:
        return []
    parts = re.split(r"[,\n]+", raw)
    return [part.strip() for part in parts if part.strip()]


def resolve_note_path(vault_path: Path, paths: NotePaths, reference: str) -> Optional[Path]:
    """Resolve a note reference to an existing vault-relative path.

    Accepts:
      - ``Project Memory/project/Runs/2026-04-11-1530-foo.md`` (full relative path)
      - ``2026-04-11-1530-foo`` (file stem, searched under the project)
      - ``Decisions`` / ``MOC`` / ``Project Home`` (hub short names)
      - ``[[2026-04-11-1530-foo]]`` (wikilink form)
    Returns ``None`` when nothing matches; callers should warn but not abort.
    """
    raw = reference.strip()
    if not raw:
        return None
    # Strip wikilink wrappers if provided.
    wikilink_match = re.match(r"^\[\[(.+?)\]\]$", raw)
    if wikilink_match:
        raw = wikilink_match.group(1).strip()
    # Full relative path under Project Memory/.
    candidate = Path(raw)
    if candidate.suffix.lower() == ".md":
        absolute = vault_path / candidate
        if absolute.exists():
            return candidate
    else:
        # Try as relative path with .md appended.
        with_ext = Path(raw + ".md")
        if (vault_path / with_ext).exists():
            return with_ext

    # Treat as short name — search within the project directory by stem.
    project_abs = vault_path / paths.project_dir
    if not project_abs.exists():
        return None
    target_stem = raw
    for md_file in project_abs.rglob("*.md"):
        if md_file.stem == target_stem:
            return md_file.relative_to(vault_path)
    return None


def _related_entry(target_stem: str, reason: Optional[str]) -> str:
    base = f"- [[{target_stem}]]"
    if reason and reason.strip():
        return f"{base} — {reason.strip()}"
    return base


def _has_link_to(body: str, target_stem: str) -> bool:
    """Return True if ``body`` already contains a wikilink to ``target_stem``."""
    pattern = re.compile(r"\[\[" + re.escape(target_stem) + r"(?:\|[^\]]*)?\]\]")
    return pattern.search(body) is not None


def _append_to_related_section(body: str, entry: str) -> str:
    """Insert ``entry`` into an existing ``## Related`` section, or append a new one.

    The function is idempotent for the section itself — duplicate entries are
    filtered by the caller via ``_has_link_to``.
    """
    if RELATED_HEADING in body:
        # Insert the entry at the end of the Related section (before the next
        # heading or EOF). We split once on the heading, locate the section's
        # end, and splice the new line in.
        head, _, tail = body.partition(RELATED_HEADING)
        lines = tail.splitlines()
        # Find the first subsequent heading (## or #) that terminates the section.
        end_index = len(lines)
        for idx, line in enumerate(lines[1:], start=1):  # skip the heading line itself
            stripped = line.lstrip()
            if stripped.startswith("## ") or stripped.startswith("# "):
                end_index = idx
                break
        # Trim trailing blank lines inside the section so the new entry sits flush.
        insert_at = end_index
        while insert_at > 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        new_lines = lines[:insert_at] + [entry] + lines[insert_at:]
        return head + RELATED_HEADING + "\n".join(new_lines)
    # No section yet — append one at EOF with a blank line before it.
    separator = "" if body.endswith("\n\n") else ("\n" if body.endswith("\n") else "\n\n")
    return body + separator + RELATED_HEADING + "\n\n" + entry + "\n"


def ensure_related_link(
    cli: ObsidianCLI,
    note_path: Path,
    target_stem: str,
    reason: Optional[str],
) -> str:
    """Ensure ``note_path`` contains a ``## Related`` link to ``target_stem``.

    Idempotent: if the link already exists anywhere in the note, returns
    ``skipped``. Uses direct file writes (not Obsidian CLI append) because the
    operation needs to read, parse sections, and write atomically.
    """
    absolute = cli.vault_path / note_path
    if not absolute.exists():
        return f"missing:{note_path.as_posix()}"
    if target_stem == note_path.stem:
        return f"self:{note_path.as_posix()}"
    if cli.dry_run:
        return f"[dry-run] weave {note_path.as_posix()} ← [[{target_stem}]]"
    body = absolute.read_text(encoding="utf-8")
    if _has_link_to(body, target_stem):
        return f"skipped:{note_path.as_posix()} (already linked)"
    updated = _append_to_related_section(body, _related_entry(target_stem, reason))
    if not updated.endswith("\n"):
        updated += "\n"
    absolute.write_text(updated, encoding="utf-8")
    return f"linked:{note_path.as_posix()} ← [[{target_stem}]]"


def weave_bidirectional(
    cli: ObsidianCLI,
    source_path: Path,
    neighbor_paths: List[Path],
    reason: Optional[str] = None,
) -> List[str]:
    """Create A↔B edges between ``source_path`` and each neighbor.

    Returns a list of human-readable status strings (one per edge attempt,
    two statuses per neighbor: forward + reverse).
    """
    results: List[str] = []
    source_stem = source_path.stem
    for neighbor in neighbor_paths:
        neighbor_stem = neighbor.stem
        forward = ensure_related_link(cli, source_path, neighbor_stem, reason)
        results.append(f"→ {forward}")
        reverse = ensure_related_link(cli, neighbor, source_stem, reason)
        results.append(f"← {reverse}")
    return results


def _parse_search_output_paths(output: str) -> List[str]:
    """Extract vault-relative note paths from Obsidian CLI search output.

    The Obsidian CLI ``search`` command prints result lines that include the
    matching file path. Formats have varied across versions, so this parser
    accepts any line containing a ``.md`` token under ``Project Memory/``.
    """
    paths: List[str] = []
    seen = set()
    for line in output.splitlines():
        match = re.search(r"(Project Memory/[^\s\"'`]+\.md)", line)
        if not match:
            continue
        candidate = match.group(1)
        if candidate in seen:
            continue
        seen.add(candidate)
        paths.append(candidate)
    return paths


def auto_discover_neighbors(
    cli: ObsidianCLI,
    paths: NotePaths,
    query: str,
    limit: int,
    exclude: Optional[Path] = None,
) -> List[Path]:
    """Run an Obsidian search scoped to the project and return the top N notes.

    ``exclude`` is used so a just-written run note never links to itself.
    Hub notes (Project Home, MOC, Run Log, Decisions, Open Questions) are
    skipped because ``record-run`` already writes those in the header.
    """
    if not query.strip() or limit <= 0:
        return []
    or_query = _build_or_query(query)
    scoped_query = f"{or_query} path:\"{PROJECT_ROOT}/{paths.project_slug}\""
    try:
        output = cli.run("search", f"query={scoped_query}")
    except RuntimeError as exc:
        print(f"auto-relate: search failed, skipping weave ({exc})")
        return []
    hub_stems = {
        paths.home.stem,
        paths.moc.stem,
        paths.run_log.stem,
        paths.decisions.stem,
        paths.questions.stem,
        paths.architecture.stem,
        paths.roadmap.stem,
        paths.debugging_notes.stem,
        paths.release_notes.stem,
        paths.current_memory.stem,
    }
    results: List[Path] = []
    for raw_path in _parse_search_output_paths(output):
        candidate = Path(raw_path)
        if exclude and candidate == exclude:
            continue
        if candidate.stem in hub_stems:
            continue
        if not (cli.vault_path / candidate).exists():
            continue
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Compaction helpers
# ---------------------------------------------------------------------------


@dataclass
class RunMemory:
    path: Path
    stem: str
    title: str
    created: str
    tags: List[str]
    prompt: str
    summary: str
    actions: str
    decisions: str
    questions: str
    keywords: List[str]


@dataclass
class TopicMemory:
    key: str
    title: str
    path: Path
    runs: List[RunMemory]
    keywords: List[str]
    related: List[str]


def _extract_frontmatter(body: str) -> Dict[str, object]:
    if not body.startswith("---\n"):
        return {}
    end = body.find("\n---", 4)
    if end == -1:
        return {}
    data: Dict[str, object] = {}
    current_list: Optional[str] = None
    for raw_line in body[4:end].splitlines():
        if raw_line.startswith("  - ") and current_list:
            values = data.setdefault(current_list, [])
            if isinstance(values, list):
                values.append(raw_line[4:].strip().strip('"'))
            continue
        current_list = None
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list = key
        else:
            data[key] = value.strip('"')
    return data


def _frontmatter_body(body: str) -> Tuple[str, str]:
    if not body.startswith("---\n"):
        return "", body
    end = body.find("\n---", 4)
    if end == -1:
        return "", body
    split_at = end + len("\n---")
    return body[:split_at], body[split_at:].lstrip("\n")


def _section(body: str, heading: str) -> str:
    pattern = re.compile(
        r"^## " + re.escape(heading) + r"\s*$\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    if not match:
        return ""
    return match.group("body").strip()


def _plain_sentences(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned or cleaned.lower() == "none.":
        return []
    parts = re.split(r"(?<=[.!?])\s+|;\s+", cleaned)
    return [part.strip(" -") for part in parts if len(part.strip(" -")) >= 12]


def _keywords(text: str, tags: Optional[Iterable[str]] = None, limit: int = 12) -> List[str]:
    counts: Dict[str, int] = {}
    for tag in tags or []:
        token = slugify(tag)
        if token and token not in STOP_WORDS and token not in {"run", "compacted"}:
            counts[token] = counts.get(token, 0) + 5
    for token in re.findall(r"[A-Za-z][A-Za-z0-9.+_-]{2,}", text.lower()):
        normalized = slugify(token)
        if not normalized or normalized in STOP_WORDS or len(normalized) < 3:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _count in ranked[:limit]]


def _topic_title(key: str) -> str:
    return " ".join(part.upper() if len(part) <= 4 else part.capitalize() for part in key.split("-"))


def _compact_topic_key(run: RunMemory, project_slug: str) -> str:
    ignored_tags = {
        project_slug,
        "run",
        "bugfix",
        "fix",
        "setup",
        "memory-bank",
        "memory",
        "cli",
        "test",
        "tests",
        "workflow",
        "claude",
        "hyperprompt",
        "auto-log",
        "auto",
        "log",
        "codex",
        "notify",
        "hook",
        "turn",
        "swift",
        "adopt",
        "all",
        "none",
        "app",
        "build",
        "confirmed",
        "main",
        "changes",
        "change",
        "added",
        "found",
        "already",
    }
    combined = " ".join([run.title, run.prompt, run.summary, run.actions, run.decisions, run.questions]).lower()
    for key, pattern in TOPIC_RULES:
        if re.search(pattern, combined):
            return key
    for tag in run.tags:
        normalized = slugify(tag)
        if normalized and normalized not in ignored_tags and normalized not in STOP_WORDS:
            return normalized
    for keyword in run.keywords:
        if keyword not in ignored_tags and keyword not in STOP_WORDS:
            return keyword
    return "general"


def _parse_run_memory(
    vault_path: Path,
    relative_path: Path,
    *,
    include_compacted: bool = False,
) -> Optional[RunMemory]:
    absolute = vault_path / relative_path
    if not absolute.exists():
        return None
    body = absolute.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(body)
    if frontmatter.get("status") == "compacted" and not include_compacted:
        return None
    tags_raw = frontmatter.get("tags", [])
    tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
    title = str(frontmatter.get("title") or absolute.stem)
    prompt = _section(body, "Prompt")
    summary = _section(body, "Summary")
    actions = _section(body, "Actions Taken")
    decisions = _section(body, "Decisions")
    questions = _section(body, "Open Questions")
    combined = " ".join([title, prompt, summary, actions, decisions, questions])
    return RunMemory(
        path=relative_path,
        stem=relative_path.stem,
        title=title,
        created=str(frontmatter.get("created") or ""),
        tags=tags,
        prompt=prompt,
        summary=summary,
        actions=actions,
        decisions=decisions,
        questions=questions,
        keywords=_keywords(combined, tags=tags),
    )


def _unique_sentences(values: Iterable[str], limit: int) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        for sentence in _plain_sentences(value):
            key = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(sentence)
            if len(result) >= limit:
                return result
    return result


def _gotcha_sentences(runs: List[RunMemory], limit: int) -> List[Tuple[str, RunMemory]]:
    matches: List[Tuple[str, RunMemory]] = []
    seen: set[str] = set()
    for run in runs:
        text = " ".join([run.prompt, run.summary, run.actions, run.decisions, run.questions])
        for sentence in _plain_sentences(text):
            lowered = sentence.lower()
            if not _contains_gotcha_word(lowered):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
            if key in seen:
                continue
            seen.add(key)
            matches.append((sentence, run))
            if len(matches) >= limit:
                return matches
    return matches


def _contains_gotcha_word(sentence: str) -> bool:
    for word in GOTCHA_WORDS:
        pattern = r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
        if re.search(pattern, sentence):
            return True
    return False


def _build_topics(paths: NotePaths, runs: List[RunMemory]) -> List[TopicMemory]:
    grouped: Dict[str, List[RunMemory]] = {}
    for run in runs:
        grouped.setdefault(_compact_topic_key(run, paths.project_slug), []).append(run)

    topics: List[TopicMemory] = []
    for key, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        text = " ".join(
            " ".join([run.title, run.summary, run.actions, run.decisions, run.questions])
            for run in group
        )
        keywords = _keywords(text, tags=[key], limit=12)
        title = _topic_title(key)
        path = paths.topics_dir / f"{sanitize_note_title_component(title)}.md"
        topics.append(TopicMemory(key=key, title=title, path=path, runs=group, keywords=keywords, related=[]))

    for topic in topics:
        scores: List[Tuple[int, str]] = []
        topic_sources = {run.stem for run in topic.runs}
        topic_keywords = set(topic.keywords)
        for other in topics:
            if other.key == topic.key:
                continue
            shared_keywords = len(topic_keywords.intersection(other.keywords))
            shared_sources = len(topic_sources.intersection({run.stem for run in other.runs}))
            score = shared_keywords + shared_sources * 3
            if score > 0:
                scores.append((score, other.key))
        topic.related = [key for _score, key in sorted(scores, key=lambda item: (-item[0], item[1]))[:3]]
    return topics


def _topic_by_key(topics: List[TopicMemory]) -> Dict[str, TopicMemory]:
    return {topic.key: topic for topic in topics}


def _wikilink(path_or_stem: Path | str) -> str:
    stem = path_or_stem.stem if isinstance(path_or_stem, Path) else Path(path_or_stem).stem
    return f"[[{stem}]]"


def _write_note(cli: ObsidianCLI, relative_path: Path, content: str) -> str:
    if cli.dry_run:
        return f"[dry-run] write {relative_path.as_posix()}"
    absolute = cli.vault_path / relative_path
    absolute.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    absolute.write_text(content, encoding="utf-8")
    return f"wrote:{relative_path.as_posix()}"


def _build_topic_note(project: str, paths: NotePaths, topic: TopicMemory, topics: List[TopicMemory]) -> str:
    by_key = _topic_by_key(topics)
    summaries = _unique_sentences((run.summary for run in topic.runs), COMPACTION_NOTE_LIMIT)
    decisions = _unique_sentences((run.decisions for run in topic.runs if run.decisions.lower() != "none."), 10)
    actions = _unique_sentences((run.actions for run in topic.runs), 10)
    gotchas = _gotcha_sentences(topic.runs, 10)
    source_runs = topic.runs[:COMPACTION_SOURCE_LIMIT]

    lines = [
        build_frontmatter(
            note_type="topic-memory",
            project=project,
            tags=["topic-memory", "compacted", paths.project_slug, topic.key],
            extra={"topic": topic.title},
        ),
        "",
        f"# {topic.title}",
        "",
        f"Current memory: [[{paths.current_memory.stem}]]",
        f"MOC: [[{paths.moc.stem}]]",
        "",
        "## Key Takeaways",
    ]
    lines.extend(f"- {item}" for item in summaries or ["No durable summary extracted yet."])
    lines.extend(["", "## Gotchas"])
    lines.extend(
        f"- {sentence} Source: [[{run.stem}]]" for sentence, run in gotchas
    )
    if not gotchas:
        lines.append("- None extracted.")
    lines.extend(["", "## Decisions"])
    lines.extend(f"- {item}" for item in decisions or ["None extracted."])
    lines.extend(["", "## Useful Actions"])
    lines.extend(f"- {item}" for item in actions or ["None extracted."])
    lines.extend(["", "## Related Topics"])
    related_topics = [by_key[key] for key in topic.related if key in by_key]
    lines.extend(f"- [[{related.path.stem}]]" for related in related_topics)
    if not related_topics:
        lines.append("- None yet.")
    lines.extend(["", "## Source Runs"])
    lines.extend(f"- [[{run.stem}]]: {run.summary or run.title}" for run in source_runs)
    if len(topic.runs) > len(source_runs):
        lines.append(f"- {len(topic.runs) - len(source_runs)} additional archived source run(s) omitted from this list.")
    return "\n".join(lines)


def _build_current_memory_note(
    project: str,
    paths: NotePaths,
    compaction_path: Path,
    topics: List[TopicMemory],
    runs: List[RunMemory],
) -> str:
    gotchas = _gotcha_sentences(runs, COMPACTION_NOTE_LIMIT)
    decisions = _unique_sentences((run.decisions for run in runs if run.decisions.lower() != "none."), COMPACTION_NOTE_LIMIT)
    top_topics = topics[:20]
    lines = [
        build_frontmatter(
            note_type="current-memory",
            project=project,
            tags=["current-memory", "compacted", paths.project_slug],
            extra={"source_runs": str(len(runs))},
        ),
        "",
        f"# {paths.current_memory.stem}",
        "",
        f"Parent note: [[{paths.home.stem}]]",
        f"MOC: [[{paths.moc.stem}]]",
        f"Latest compaction: [[{compaction_path.stem}]]",
        "",
        "## High-Signal Memory",
    ]
    for topic in top_topics:
        preview = _unique_sentences((run.summary for run in topic.runs), 1)
        suffix = f" — {preview[0]}" if preview else ""
        lines.append(f"- [[{topic.path.stem}]] ({len(topic.runs)} source run(s)){suffix}")
    if not top_topics:
        lines.append("- No topics compacted yet.")
    lines.extend(["", "## Important Gotchas"])
    lines.extend(f"- {sentence} Source: [[{run.stem}]]" for sentence, run in gotchas)
    if not gotchas:
        lines.append("- None extracted.")
    lines.extend(["", "## Durable Decisions"])
    lines.extend(f"- {item}" for item in decisions or ["None extracted."])
    lines.extend(["", "## Archive"])
    lines.append(f"- Archived raw source runs live under `{paths.archived_runs_dir.as_posix()}`.")
    lines.append("- Raw runs remain available as evidence, but retrieval should start from this note and topic notes.")
    return "\n".join(lines)


def _build_compaction_note(
    project: str,
    paths: NotePaths,
    compaction_path: Path,
    topics: List[TopicMemory],
    runs: List[RunMemory],
) -> str:
    gotchas = _gotcha_sentences(runs, COMPACTION_NOTE_LIMIT)
    lines = [
        build_frontmatter(
            note_type="compaction",
            project=project,
            tags=["compaction", "archive", paths.project_slug],
            extra={"source_runs": str(len(runs))},
        ),
        "",
        f"# {compaction_path.stem}",
        "",
        f"Current memory: [[{paths.current_memory.stem}]]",
        f"MOC: [[{paths.moc.stem}]]",
        "",
        "## Result",
        f"- Compacted {len(runs)} raw run note(s) into {len(topics)} topic note(s).",
        f"- Archived source run notes under `{paths.archived_runs_dir.as_posix()}` without deleting them.",
        "- Pruned raw run links from hub indexes so the graph starts from distilled memory.",
        "",
        "## Topics",
    ]
    lines.extend(f"- [[{topic.path.stem}]]: {len(topic.runs)} source run(s)" for topic in topics)
    lines.extend(["", "## Gotchas Preserved"])
    lines.extend(f"- {sentence} Source: [[{run.stem}]]" for sentence, run in gotchas)
    if not gotchas:
        lines.append("- None extracted.")
    lines.extend(["", "## Source Runs"])
    for run in runs[:COMPACTION_SOURCE_LIMIT]:
        lines.append(f"- [[{run.stem}]]: {run.summary or run.title}")
    if len(runs) > COMPACTION_SOURCE_LIMIT:
        lines.append(f"- {len(runs) - COMPACTION_SOURCE_LIMIT} additional archived source run(s) omitted from this list.")
    return "\n".join(lines)


def _without_related_section(body: str) -> str:
    pattern = re.compile(r"\n?## Related\s*\n.*?(?=\n## |\Z)", re.MULTILINE | re.DOTALL)
    return pattern.sub("", body).rstrip() + "\n"


def _archive_run_body(
    project: str,
    run: RunMemory,
    original_body: str,
    compaction_path: Path,
    topic_paths: List[Path],
) -> str:
    frontmatter, content = _frontmatter_body(original_body)
    metadata = build_frontmatter(
        note_type="run",
        project=project,
        tags=run.tags,
        extra={
            "title": run.title,
            "status": "compacted",
            "compacted_into": compaction_path.stem,
        },
    )
    content = _without_related_section(content)
    header_lines = [
        "",
        "## Archived Source",
        f"- Compacted into [[{compaction_path.stem}]].",
    ]
    header_lines.extend(f"- Topic: [[{topic_path.stem}]]" for topic_path in topic_paths[:3])
    header = "\n".join(header_lines)
    if "## Archived Source" in content:
        content = re.sub(
            r"## Archived Source\s*\n.*?(?=\n## |\Z)",
            header.strip(),
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        content = content.rstrip() + "\n" + header
    # Remove old hub breadcrumbs from archived runs; the compaction and topic
    # links are the deliberate graph edges now.
    content = re.sub(
        r"^(Parent note|MOC|Run log|Decision register|Question log): .*$\n?",
        "",
        content,
        flags=re.MULTILINE,
    )
    return metadata + "\n\n" + content.strip() + "\n"


def _archive_runs(
    cli: ObsidianCLI,
    project: str,
    paths: NotePaths,
    compaction_path: Path,
    topics: List[TopicMemory],
) -> List[Tuple[Path, Path]]:
    topic_for_run: Dict[str, List[Path]] = {}
    for topic in topics:
        for run in topic.runs:
            topic_for_run.setdefault(run.stem, []).append(topic.path)

    moved: List[Tuple[Path, Path]] = []
    for topic in topics:
        for run in topic.runs:
            source_abs = cli.vault_path / run.path
            if not source_abs.exists():
                continue
            dest = paths.archived_runs_dir / run.path.name
            dest_abs = cli.vault_path / dest
            suffix = 2
            while dest_abs.exists() and dest_abs != source_abs:
                dest = paths.archived_runs_dir / f"{run.path.stem}-{suffix}.md"
                dest_abs = cli.vault_path / dest
                suffix += 1
            if cli.dry_run:
                moved.append((run.path, dest))
                continue
            body = source_abs.read_text(encoding="utf-8")
            archived_body = _archive_run_body(
                project,
                run,
                body,
                compaction_path,
                topic_for_run.get(run.stem, []),
            )
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            dest_abs.write_text(archived_body, encoding="utf-8")
            if dest_abs != source_abs:
                source_abs.unlink()
            moved.append((run.path, dest))
    return moved


def _archive_stale_topics(
    cli: ObsidianCLI,
    paths: NotePaths,
    active_topic_paths: List[Path],
    compaction_path: Path,
) -> int:
    topics_dir = cli.vault_path / paths.topics_dir
    if not topics_dir.exists():
        return 0
    active_names = {path.name for path in active_topic_paths}
    archived = 0
    for topic_abs in sorted(topics_dir.glob("*.md")):
        if topic_abs.name in active_names:
            continue
        source = topic_abs.relative_to(cli.vault_path)
        dest = paths.archived_topics_dir / topic_abs.name
        dest_abs = cli.vault_path / dest
        suffix = 2
        while dest_abs.exists():
            dest = paths.archived_topics_dir / f"{topic_abs.stem}-{suffix}.md"
            dest_abs = cli.vault_path / dest
            suffix += 1
        if cli.dry_run:
            archived += 1
            continue
        body = topic_abs.read_text(encoding="utf-8")
        body = _without_related_section(body)
        body = body.rstrip() + "\n\n## Archived Topic\n"
        body += f"- Superseded by [[{compaction_path.stem}]].\n"
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        dest_abs.write_text(body, encoding="utf-8")
        topic_abs.unlink()
        archived += 1
    return archived


def _remove_lines_linking_stems(cli: ObsidianCLI, relative_path: Path, stems: set[str]) -> int:
    absolute = cli.vault_path / relative_path
    if not absolute.exists():
        return 0
    body = absolute.read_text(encoding="utf-8")
    removed = 0
    kept: List[str] = []
    for line in body.splitlines():
        links = set(_extract_wikilinks(line))
        if links.intersection(stems):
            removed += 1
            continue
        kept.append(line)
    if removed and not cli.dry_run:
        absolute.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return removed


def _append_unique_line(cli: ObsidianCLI, relative_path: Path, line: str) -> None:
    absolute = cli.vault_path / relative_path
    if cli.dry_run:
        return
    if not absolute.exists():
        return
    body = absolute.read_text(encoding="utf-8")
    if line in body:
        return
    separator = "" if body.endswith("\n") else "\n"
    absolute.write_text(body + separator + line + "\n", encoding="utf-8")


def _collect_uncompacted_runs(
    vault_path: Path,
    paths: NotePaths,
    limit: Optional[int],
    *,
    include_archive: bool = False,
) -> List[RunMemory]:
    runs: List[RunMemory] = []
    source_dirs = [paths.runs_dir]
    if include_archive:
        source_dirs.append(paths.archived_runs_dir)
    for source_dir in source_dirs:
        absolute_dir = vault_path / source_dir
        if not absolute_dir.exists():
            continue
        for note in sorted(absolute_dir.glob("*.md")):
            parsed = _parse_run_memory(
                vault_path,
                note.relative_to(vault_path),
                include_compacted=source_dir == paths.archived_runs_dir,
            )
            if parsed:
                runs.append(parsed)
            if limit and len(runs) >= limit:
                return runs
    return runs


def cmd_set_vault(args: argparse.Namespace) -> None:
    store = ConfigStore()
    vault_path = Path(args.vault_path).expanduser()
    ensure_vault_ready(vault_path)
    workspace = Path(args.workspace).expanduser() if args.workspace else Path.cwd()
    store.set_vault(vault_path=vault_path, workspace=workspace)
    print(f"Saved vault: {vault_path.resolve()} for workspace: {workspace.resolve()}")


def resolve_vault_or_exit(workspace_arg: Optional[str]) -> Path:
    store = ConfigStore()
    workspace = resolve_workspace_path(workspace_arg)
    vault = store.resolve_vault(workspace=workspace)
    if not vault:
        raise SystemExit(
            "No saved vault for this workspace. Ask user for an absolute vault path, then run:\n"
            "python3 scripts/obsidian_memory.py set-vault --vault-path \"/absolute/path/to/vault\""
        )
    vault_path = Path(vault).expanduser()
    ensure_vault_ready(vault_path)
    return vault_path


def cmd_show_vault(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    print(vault_path)


def cmd_bootstrap(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project = args.project.strip()
    bootstrap_project(cli, project)


def cmd_record_run(args: argparse.Namespace) -> None:
    store = ConfigStore()
    workspace = resolve_workspace_path(args.workspace)
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project = args.project.strip()
    paths = bootstrap_project(cli, project)

    run_slug = slugify(args.title) or "run"
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    run_note_path = paths.runs_dir / f"{timestamp}-{run_slug}.md"
    run_tags = parse_tags(args.tags) + [paths.project_slug, "run"]
    frontmatter = build_frontmatter(
        note_type="run",
        project=project,
        tags=run_tags,
        extra={"title": args.title.strip()},
    )
    run_note = "\n".join(
        [
            frontmatter,
            "",
            f"# {args.title.strip()}",
            "",
            f"Parent note: [[{paths.home.stem}]]",
            f"MOC: [[{paths.moc.stem}]]",
            f"Run log: [[{paths.run_log.stem}]]",
            f"Decision register: [[{paths.decisions.stem}]]",
            f"Question log: [[{paths.questions.stem}]]",
            "",
            "## Prompt",
            args.prompt.strip(),
            "",
            "## Summary",
            args.summary.strip(),
            "",
            "## Actions Taken",
            args.actions.strip(),
            "",
            "## Decisions",
            args.decisions.strip() if args.decisions else "None.",
            "",
            "## Open Questions",
            args.questions.strip() if args.questions else "None.",
        ]
    )
    cli.ensure_note(run_note_path, run_note)
    cli.append(
        paths.run_log,
        f"- [[{run_note_path.stem}]]: {args.summary.strip()}",
    )
    cli.append(
        paths.moc,
        f"- [[{run_note_path.stem}]]: {args.summary.strip()}",
    )
    if args.decisions:
        cli.append(paths.decisions, f"- [[{run_note_path.stem}]]: {args.decisions.strip()}")
    if args.questions:
        cli.append(paths.questions, f"- [[{run_note_path.stem}]]: {args.questions.strip()}")
    print(f"Recorded run note: {run_note_path.as_posix()}")

    # Bidirectional weaving — runs automatically unless explicitly disabled.
    neighbor_paths: List[Path] = []
    explicit_refs = _parse_related_arg(getattr(args, "related", None))
    for ref in explicit_refs:
        resolved = resolve_note_path(vault_path, paths, ref)
        if resolved is None:
            print(f"auto-relate: could not resolve '{ref}' — skipped")
            continue
        if resolved == run_note_path:
            continue
        if resolved not in neighbor_paths:
            neighbor_paths.append(resolved)

    auto_mode = not getattr(args, "no_auto_relate", False)
    limit = int(getattr(args, "auto_relate_limit", 5) or 5)
    if auto_mode and len(neighbor_paths) < limit:
        query = getattr(args, "auto_relate_query", None)
        if not query:
            # Derive a query from the title + tags: strong lexical signal, cheap.
            derived = [args.title.strip()]
            if args.tags:
                derived.append(args.tags.replace(",", " "))
            query = " ".join(derived).strip()
        remaining = limit - len(neighbor_paths)
        discovered = auto_discover_neighbors(
            cli,
            paths,
            query,
            remaining,
            exclude=run_note_path,
        )
        for candidate in discovered:
            if candidate not in neighbor_paths:
                neighbor_paths.append(candidate)

    if neighbor_paths:
        print(f"auto-relate: weaving {len(neighbor_paths)} neighbor(s)")
        reason = args.summary.strip() or None
        for status in weave_bidirectional(cli, run_note_path, neighbor_paths, reason):
            print(f"  {status}")
    elif auto_mode:
        print("auto-relate: no neighbors found (run becomes a root node)")
    audit_every = store.get_audit_every_runs()
    if audit_every <= 0:
        return
    run_count = store.bump_run_counter(workspace, paths.project_slug)
    if run_count < audit_every:
        print(f"Auto-audit: skipped ({run_count}/{audit_every} runs).")
        return
    print(f"Auto-audit: threshold reached ({run_count}/{audit_every}), running audit.")
    run_audit_checks(cli, paths)
    store.reset_run_counter(workspace, paths.project_slug)


def _build_or_query(raw_query: str) -> str:
    """Join multi-word queries with OR so each keyword contributes results.

    Obsidian search AND-matches space-separated terms by default, which
    causes zero results when not all keywords appear in the same note.
    Wrapping in ``(word1 OR word2 OR ...)`` makes each keyword additive.
    Single-word queries are passed through unchanged.
    """
    words = raw_query.split()
    if len(words) <= 1:
        return raw_query
    return "(" + " OR ".join(words) + ")"


def cmd_search(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project_slug = slugify(args.project)
    or_query = _build_or_query(args.query)
    scoped_query = f"{or_query} path:\"{PROJECT_ROOT}/{project_slug}\""
    output = cli.run("search", f"query={scoped_query}")
    print(output)


def cmd_read_note(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    output = cli.read(Path(args.path))
    print(output)


def cmd_link_notes(args: argparse.Namespace) -> None:
    """Weave bidirectional ``## Related`` links between existing notes.

    Unlike ``record-run --auto-relate`` (which fires at creation time), this
    command targets nodes that already exist — use it to retrofit a
    star-shaped vault or to add edges discovered after the fact.
    """
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    paths = build_note_paths(args.project.strip())

    source = resolve_note_path(vault_path, paths, args.source)
    if source is None:
        raise SystemExit(f"Source note not found: {args.source}")

    target_refs = _parse_related_arg(args.target)
    if not target_refs:
        raise SystemExit("At least one --to target is required.")

    neighbor_paths: List[Path] = []
    for ref in target_refs:
        resolved = resolve_note_path(vault_path, paths, ref)
        if resolved is None:
            print(f"link-notes: could not resolve '{ref}' — skipped")
            continue
        if resolved == source:
            print(f"link-notes: '{ref}' is the source note — skipped")
            continue
        if resolved not in neighbor_paths:
            neighbor_paths.append(resolved)

    if not neighbor_paths:
        raise SystemExit("No valid target notes to link.")

    print(f"Weaving {len(neighbor_paths)} bidirectional link(s) from {source.as_posix()}")
    for status in weave_bidirectional(cli, source, neighbor_paths, args.reason):
        print(f"  {status}")


def cmd_compact_project(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project = args.project.strip()
    paths = bootstrap_project(cli, project)
    limit = args.max_runs if args.max_runs and args.max_runs > 0 else None
    runs = _collect_uncompacted_runs(
        vault_path,
        paths,
        limit,
        include_archive=getattr(args, "include_archive", False),
    )
    if not runs:
        sources = paths.runs_dir.as_posix()
        if getattr(args, "include_archive", False):
            sources += f" or {paths.archived_runs_dir.as_posix()}"
        print(f"No run notes found in {sources}.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    compaction_path = paths.compactions_dir / f"{timestamp}-compact-{paths.project_slug}.md"
    topics = _build_topics(paths, runs)

    source_label = paths.runs_dir.as_posix()
    if getattr(args, "include_archive", False):
        source_label += f" plus {paths.archived_runs_dir.as_posix()}"
    print(f"Compacting {len(runs)} run note(s) from {source_label}.")
    print(f"Distilled topic count: {len(topics)}")

    compaction_note = _build_compaction_note(project, paths, compaction_path, topics, runs)
    print(_write_note(cli, compaction_path, compaction_note))

    current_note = _build_current_memory_note(project, paths, compaction_path, topics, runs)
    print(_write_note(cli, paths.current_memory, current_note))

    for topic in topics:
        print(_write_note(cli, topic.path, _build_topic_note(project, paths, topic, topics)))
    stale_topics = _archive_stale_topics(
        cli,
        paths,
        [topic.path for topic in topics],
        compaction_path,
    )
    if stale_topics:
        print(f"Archived stale topic notes: {stale_topics} into {paths.archived_topics_dir.as_posix()}")

    # Intentional neural-network edges: distilled memory is densely linked,
    # archived source notes are sparse evidence.
    ensure_related_link(cli, paths.current_memory, compaction_path.stem, "latest compaction")
    ensure_related_link(cli, compaction_path, paths.current_memory.stem, "distilled project memory")
    for topic in topics:
        ensure_related_link(cli, paths.current_memory, topic.path.stem, f"{len(topic.runs)} source run(s)")
        ensure_related_link(cli, topic.path, paths.current_memory.stem, "current project memory")
        ensure_related_link(cli, compaction_path, topic.path.stem, f"{len(topic.runs)} source run(s)")
        ensure_related_link(cli, topic.path, compaction_path.stem, "compaction source map")
    topic_map = _topic_by_key(topics)
    for topic in topics:
        related_paths = [topic_map[key].path for key in topic.related if key in topic_map]
        if related_paths:
            weave_bidirectional(cli, topic.path, related_paths, "shared compacted context")

    moved: List[Tuple[Path, Path]] = []
    if not args.no_archive:
        moved = _archive_runs(cli, project, paths, compaction_path, topics)
        print(f"Archived source runs: {len(moved)} into {paths.archived_runs_dir.as_posix()}")
    else:
        print("Archive step skipped by --no-archive.")

    stems = {run.stem for run in runs}
    pruned = 0
    for hub in [paths.run_log, paths.moc, paths.decisions, paths.questions]:
        pruned += _remove_lines_linking_stems(cli, hub, stems)
    summary = (
        f"- [[{compaction_path.stem}]]: Compacted {len(runs)} run note(s) "
        f"into {len(topics)} topic note(s); archived raw sources under `{paths.archived_runs_dir.as_posix()}`."
    )
    _append_unique_line(cli, paths.run_log, summary)
    _append_unique_line(cli, paths.moc, summary)
    _append_unique_line(cli, paths.decisions, f"- [[{compaction_path.stem}]]: Prefer [[{paths.current_memory.stem}]] and topic notes before raw archived run notes for retrieval.")
    print(f"Pruned hub/index lines pointing at compacted runs: {pruned}")

    active_runs = len(list((vault_path / paths.runs_dir).glob("*.md"))) if (vault_path / paths.runs_dir).exists() else 0
    archived_runs = len(list((vault_path / paths.archived_runs_dir).glob("*.md"))) if (vault_path / paths.archived_runs_dir).exists() else 0
    print(f"Active run notes remaining: {active_runs}")
    print(f"Archived run notes available as evidence: {archived_runs}")
    print(f"Current memory: {paths.current_memory.as_posix()}")
    print(f"Compaction note: {compaction_path.as_posix()}")


def cmd_audit(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    paths = build_note_paths(args.project.strip())
    run_audit_checks(cli, paths)


def run_audit_checks(cli: ObsidianCLI, paths: NotePaths) -> None:
    checks = [
        ("unresolved", ["counts", "verbose"]),
        ("orphans", []),
        ("deadends", []),
        ("backlinks", [f"path={paths.home.as_posix()}", "counts"]),
    ]
    for command, command_args in checks:
        print(f"## {command}")
        output = cli.run(command, *command_args)
        print(output)
        print("")


def cmd_init_project(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project = args.project.strip()
    bootstrap_project(cli, project)
    if args.with_stub:
        stub = argparse.Namespace(
            project=project,
            title="Initial memory bank setup",
            prompt="Initialize project knowledge base from blank state.",
            summary="Created seed notes and projects index entry.",
            actions="Bootstrapped project structure and linked anchor notes.",
            decisions="Adopt per-project folder under Project Memory.",
            questions="Define topic-specific notes next.",
            tags="setup,memory-bank",
            workspace=args.workspace,
            dry_run=args.dry_run,
            related=None,
            no_auto_relate=True,  # init stub has no history to relate to
            auto_relate_query=None,
            auto_relate_limit=5,
        )
        cmd_record_run(stub)


def cmd_doctor(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).expanduser() if args.workspace else Path.cwd()
    print(f"Workspace: {workspace.resolve()}")
    store = ConfigStore()
    mapped = store.resolve_vault(workspace)
    audit_every = store.get_audit_every_runs()
    if mapped:
        print(f"Mapped vault: {mapped}")
    else:
        print("Mapped vault: <none>")
    print(f"Auto-audit frequency: every {audit_every} run(s)")
    cli_path = shutil.which("obsidian-cli") or shutil.which("obsidian")
    if cli_path:
        print(f"Obsidian CLI executable: {cli_path} (optional; file-backed mode is available)")
    else:
        print("Obsidian CLI executable: not found (OK; file-backed mode is available)")
    if not mapped:
        print("Vault mapping: MISSING (run set-vault)")
        return
    vault_path = Path(mapped).expanduser()
    ensure_vault_ready(vault_path)
    if os_access(vault_path):
        print("Vault path access: OK")
    else:
        print("Vault path access: NOT WRITABLE")


def os_access(path: Path) -> bool:
    try:
        test_dir = path / PROJECT_ROOT
        test_dir.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def cmd_set_audit_frequency(args: argparse.Namespace) -> None:
    store = ConfigStore()
    store.set_audit_every_runs(args.runs)
    print(f"Saved auto-audit frequency: every {max(0, args.runs)} run(s).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Obsidian project memory bank helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_set = subparsers.add_parser("set-vault", help="Save vault path for workspace")
    parser_set.add_argument("--vault-path", required=True, help="Absolute path to vault")
    parser_set.add_argument("--workspace", help="Workspace path to bind vault to")
    parser_set.set_defaults(func=cmd_set_vault)

    parser_show = subparsers.add_parser("show-vault", help="Show resolved vault path")
    parser_show.add_argument("--workspace", help="Workspace path override")
    parser_show.set_defaults(func=cmd_show_vault)

    parser_bootstrap = subparsers.add_parser("bootstrap", help="Create seed project notes")
    parser_bootstrap.add_argument("--project", required=True, help="Project display name")
    parser_bootstrap.add_argument("--workspace", help="Workspace path override")
    parser_bootstrap.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_bootstrap.set_defaults(func=cmd_bootstrap)

    parser_init = subparsers.add_parser(
        "init-project",
        help="Initialize project folders, seed notes, and optional first run stub",
    )
    parser_init.add_argument("--project", required=True, help="Project display name")
    parser_init.add_argument("--workspace", help="Workspace path override")
    parser_init.add_argument("--with-stub", action="store_true", help="Create starter run note")
    parser_init.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_init.set_defaults(func=cmd_init_project)

    parser_run = subparsers.add_parser("record-run", help="Create a run note and append indexes")
    parser_run.add_argument("--project", required=True, help="Project display name")
    parser_run.add_argument("--title", required=True, help="Run note title")
    parser_run.add_argument("--prompt", required=True, help="Prompt summary")
    parser_run.add_argument("--summary", required=True, help="Run summary")
    parser_run.add_argument("--actions", required=True, help="Actions taken")
    parser_run.add_argument("--decisions", help="Decision summary")
    parser_run.add_argument("--questions", help="Open questions summary")
    parser_run.add_argument("--tags", default="", help="Comma-separated tags")
    parser_run.add_argument(
        "--related",
        help=(
            "Comma-separated list of neighbor notes to link bidirectionally. "
            "Accepts file stems, short names, or vault-relative paths. "
            "Combines with --auto-relate unless --no-auto-relate is passed."
        ),
    )
    parser_run.add_argument(
        "--no-auto-relate",
        action="store_true",
        help="Disable automatic neighbor discovery; only --related links are woven.",
    )
    parser_run.add_argument(
        "--auto-relate-query",
        help="Override the search query used for automatic neighbor discovery "
             "(defaults to title + tags).",
    )
    parser_run.add_argument(
        "--auto-relate-limit",
        type=int,
        default=5,
        help="Maximum number of bidirectional neighbor links to create (default: 5).",
    )
    parser_run.add_argument("--workspace", help="Workspace path override")
    parser_run.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_run.set_defaults(func=cmd_record_run)

    parser_link = subparsers.add_parser(
        "link-notes",
        help="Create bidirectional ## Related links between existing notes",
    )
    parser_link.add_argument("--project", required=True, help="Project display name")
    parser_link.add_argument(
        "--from",
        dest="source",
        required=True,
        help="Source note (file stem, short name, or vault-relative path)",
    )
    parser_link.add_argument(
        "--to",
        dest="target",
        required=True,
        help="Target note(s) — comma-separated, same reference forms as --from",
    )
    parser_link.add_argument(
        "--reason",
        help="Optional short description appended to each '## Related' entry",
    )
    parser_link.add_argument("--workspace", help="Workspace path override")
    parser_link.add_argument("--dry-run", action="store_true", help="Print planned edits only")
    parser_link.set_defaults(func=cmd_link_notes)

    parser_search = subparsers.add_parser("search", help="Search project memory")
    parser_search.add_argument("--project", required=True, help="Project display name")
    parser_search.add_argument("--query", required=True, help="Search query")
    parser_search.add_argument("--workspace", help="Workspace path override")
    parser_search.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_search.set_defaults(func=cmd_search)

    parser_compact = subparsers.add_parser(
        "compact-project",
        help="Distill raw run notes into Current Memory, topic notes, and archived evidence",
    )
    parser_compact.add_argument("--project", required=True, help="Project display name")
    parser_compact.add_argument(
        "--max-runs",
        type=int,
        default=0,
        help="Maximum active run notes to compact (default: all uncompacted runs)",
    )
    parser_compact.add_argument(
        "--no-archive",
        action="store_true",
        help="Write distilled notes but leave raw runs in Runs/",
    )
    parser_compact.add_argument(
        "--include-archive",
        action="store_true",
        help="Also re-distill already archived source runs.",
    )
    parser_compact.add_argument("--workspace", help="Workspace path override")
    parser_compact.add_argument("--dry-run", action="store_true", help="Print planned edits only")
    parser_compact.set_defaults(func=cmd_compact_project)

    parser_read = subparsers.add_parser("read-note", help="Read one note by path")
    parser_read.add_argument("--path", required=True, help="Path relative to vault root")
    parser_read.add_argument("--workspace", help="Workspace path override")
    parser_read.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_read.set_defaults(func=cmd_read_note)

    parser_audit = subparsers.add_parser("audit", help="Audit project graph integrity")
    parser_audit.add_argument("--project", required=True, help="Project display name")
    parser_audit.add_argument("--workspace", help="Workspace path override")
    parser_audit.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_audit.set_defaults(func=cmd_audit)

    parser_doctor = subparsers.add_parser("doctor", help="Validate CLI/vault readiness")
    parser_doctor.add_argument("--workspace", help="Workspace path override")
    parser_doctor.set_defaults(func=cmd_doctor)

    parser_audit_frequency = subparsers.add_parser(
        "set-audit-frequency",
        help="Set automatic audit cadence for record-run (0 disables auto-audit)",
    )
    parser_audit_frequency.add_argument(
        "--runs",
        required=True,
        type=int,
        help="Run interval for automatic audit (e.g., 5 means every 5 runs)",
    )
    parser_audit_frequency.set_defaults(func=cmd_set_audit_frequency)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except FileNotFoundError as exc:
        if exc.filename == "obsidian":
            raise SystemExit(
                "Could not find 'obsidian' CLI in PATH. Enable/register Obsidian CLI first."
            ) from exc
        raise
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
