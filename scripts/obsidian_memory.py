#!/usr/bin/env python3
"""
Manage a project knowledge memory bank in Obsidian via Obsidian CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


SKILL_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = SKILL_ROOT / "state"
STATE_FILE = STATE_DIR / "vault_config.json"
PROJECT_ROOT = "Project Memory"


def slugify(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def normalize_workspace(path: Path) -> str:
    return str(path.resolve())


class ConfigStore:
    def __init__(self, state_file: Path = STATE_FILE) -> None:
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, object]:
        if not self.state_file.exists():
            return {"default_vault_path": "", "workspace_vaults": {}}
        with self.state_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "workspace_vaults" not in data or not isinstance(data["workspace_vaults"], dict):
            data["workspace_vaults"] = {}
        if "default_vault_path" not in data:
            data["default_vault_path"] = ""
        return data

    def save(self, data: Dict[str, object]) -> None:
        with self.state_file.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")

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


@dataclass
class NotePaths:
    project_slug: str
    project_dir: Path
    home: Path
    moc: Path
    run_log: Path
    decisions: Path
    questions: Path
    runs_dir: Path


def build_note_paths(project_name: str) -> NotePaths:
    project_slug = slugify(project_name) or "project"
    project_dir = Path(PROJECT_ROOT) / project_slug
    project_home_name = f"{project_name.strip()} Home".strip()
    if project_home_name == "Home":
        project_home_name = "Project Home"
    home = project_dir / f"{project_home_name}.md"
    moc = project_dir / "MOC.md"
    run_log = project_dir / "Run Log.md"
    decisions = project_dir / "Decisions.md"
    questions = project_dir / "Open Questions.md"
    runs_dir = project_dir / "Runs"
    return NotePaths(
        project_slug=project_slug,
        project_dir=project_dir,
        home=home,
        moc=moc,
        run_log=run_log,
        decisions=decisions,
        questions=questions,
        runs_dir=runs_dir,
    )


class ObsidianCLI:
    def __init__(self, vault_path: Path, dry_run: bool = False) -> None:
        self.vault_path = vault_path
        self.dry_run = dry_run

    def run(self, command: str, *args: str) -> str:
        cmd = ["obsidian", command, *args]
        if self.dry_run:
            printable = " ".join(cmd)
            return f"[dry-run] {printable}"
        completed = subprocess.run(
            cmd,
            cwd=self.vault_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Obsidian CLI failed ({completed.returncode}) for: {' '.join(cmd)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed.stdout.strip()

    def ensure_note(self, relative_path: Path, content: str) -> str:
        absolute = self.vault_path / relative_path
        if absolute.exists():
            return f"exists:{relative_path.as_posix()}"
        return self.run(
            "create",
            f"path={relative_path.as_posix()}",
            f"content={content}",
            "silent",
        )

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

    return {
        paths.home: home,
        paths.moc: moc,
        paths.run_log: run_log,
        paths.decisions: decisions,
        paths.questions: questions,
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


def cmd_set_vault(args: argparse.Namespace) -> None:
    store = ConfigStore()
    vault_path = Path(args.vault_path).expanduser()
    ensure_vault_ready(vault_path)
    workspace = Path(args.workspace).expanduser() if args.workspace else Path.cwd()
    store.set_vault(vault_path=vault_path, workspace=workspace)
    print(f"Saved vault: {vault_path.resolve()} for workspace: {workspace.resolve()}")


def resolve_vault_or_exit(workspace_arg: Optional[str]) -> Path:
    store = ConfigStore()
    workspace = Path(workspace_arg).expanduser() if workspace_arg else Path.cwd()
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
    paths = build_note_paths(project)
    notes = build_seed_notes(project, paths)
    print(f"Bootstrapping project memory in vault: {vault_path}")
    for relative_path, content in notes.items():
        result = cli.ensure_note(relative_path, content)
        print(f"- {relative_path.as_posix()}: {result or 'created'}")


def cmd_record_run(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project = args.project.strip()
    paths = build_note_paths(project)
    notes = build_seed_notes(project, paths)
    for relative_path, content in notes.items():
        cli.ensure_note(relative_path, content)

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
    if args.decisions:
        cli.append(paths.decisions, f"- [[{run_note_path.stem}]]: {args.decisions.strip()}")
    if args.questions:
        cli.append(paths.questions, f"- [[{run_note_path.stem}]]: {args.questions.strip()}")
    print(f"Recorded run note: {run_note_path.as_posix()}")


def cmd_search(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    project_slug = slugify(args.project)
    scoped_query = f"{args.query} path:\"{PROJECT_ROOT}/{project_slug}\""
    output = cli.run("search", f"query={scoped_query}")
    print(output)


def cmd_read_note(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    output = cli.read(Path(args.path))
    print(output)


def cmd_audit(args: argparse.Namespace) -> None:
    vault_path = resolve_vault_or_exit(args.workspace)
    cli = ObsidianCLI(vault_path=vault_path, dry_run=args.dry_run)
    paths = build_note_paths(args.project.strip())
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

    parser_run = subparsers.add_parser("record-run", help="Create a run note and append indexes")
    parser_run.add_argument("--project", required=True, help="Project display name")
    parser_run.add_argument("--title", required=True, help="Run note title")
    parser_run.add_argument("--prompt", required=True, help="Prompt summary")
    parser_run.add_argument("--summary", required=True, help="Run summary")
    parser_run.add_argument("--actions", required=True, help="Actions taken")
    parser_run.add_argument("--decisions", help="Decision summary")
    parser_run.add_argument("--questions", help="Open questions summary")
    parser_run.add_argument("--tags", default="", help="Comma-separated tags")
    parser_run.add_argument("--workspace", help="Workspace path override")
    parser_run.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser_run.set_defaults(func=cmd_record_run)

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
