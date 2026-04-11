#!/usr/bin/env python3
"""
Manage a project knowledge memory bank in Obsidian via Obsidian CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


SKILL_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = SKILL_ROOT / "state"
STATE_FILE = STATE_DIR / "vault_config.json"
PROJECT_ROOT = "Project Memory"
PROJECTS_INDEX_PATH = Path(PROJECT_ROOT) / "Projects Index.md"
DEFAULT_AUDIT_EVERY_RUNS = 5


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
    def __init__(self, state_file: Path = STATE_FILE) -> None:
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
        runs_dir=runs_dir,
    )


class ObsidianCLI:
    def __init__(self, vault_path: Path, dry_run: bool = False) -> None:
        self.vault_path = vault_path
        self.dry_run = dry_run

    def run(self, command: str, *args: str, retries: int = 2) -> str:
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


def ensure_project_dirs(vault_path: Path, paths: NotePaths, dry_run: bool) -> None:
    targets = [vault_path / paths.project_dir, vault_path / paths.runs_dir]
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
    try:
        version = subprocess.run(
            ["obsidian", "version"],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        raise SystemExit("Doctor failed: obsidian CLI is not installed or not in PATH.")
    if version.returncode != 0 or _contains_cli_error(version.stdout) or _contains_cli_error(version.stderr):
        raise SystemExit(
            "Doctor failed: obsidian CLI could not reach app successfully.\n"
            f"stdout:\n{version.stdout}\n"
            f"stderr:\n{version.stderr}"
        )
    print("Obsidian CLI: OK")
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
