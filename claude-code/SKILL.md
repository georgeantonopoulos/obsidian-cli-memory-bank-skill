---
name: obsidian-memory
description: Build and maintain project-specific Obsidian knowledge bases via the obmem CLI. Use when an agent needs to (1) persist a vault mapping for a workspace, (2) capture prompt/run context as structured Markdown notes, (3) auto-link notes with wikilinks for backlink coverage, (4) retrieve context via search/read commands, or (5) audit graph hygiene with unresolved/orphan/dead-end link checks.
---

# Obsidian CLI Memory Bank

## Overview

Use this skill to maintain a per-project "memory bank" inside Obsidian with consistent note structure, dense wikilinking, and CLI-first retrieval.
Persist the vault path once per workspace, then bootstrap/update project notes on every relevant run.

## Prerequisites

- `obmem` CLI installed via pipx (`pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git`)
- Obsidian desktop running with Obsidian CLI enabled
- `obsidian` CLI available in PATH

## Workflow

All commands use the `obmem` CLI directly (installed via pipx).

### 1) Resolve vault first

```bash
obmem show-vault
```

If no vault is set for the current workspace:

1. Ask exactly one question: `Which absolute vault path should I use for this project?`
2. Save it:

```bash
obmem set-vault --vault-path "/absolute/path/to/vault"
```

Use `--workspace "/path/to/project"` when setting or resolving a different workspace than the current directory.

### 2) Bootstrap project memory structure

Create core notes once per project:

```bash
obmem bootstrap --project "ProjectName"
```

Or run the one-command initializer:

```bash
obmem init-project --project "ProjectName" --with-stub
```

This creates:

- `Project Memory/<project-slug>/<Project Home>.md`
- `Project Memory/<project-slug>/MOC.md`
- `Project Memory/<project-slug>/Run Log.md`
- `Project Memory/<project-slug>/Decisions.md`
- `Project Memory/<project-slug>/Open Questions.md`

All seed notes include wikilinks to each other so backlinks are available immediately.

### 3) Record each meaningful run

After a task, add a run note:

```bash
obmem record-run \
  --project "ProjectName" \
  --title "Fix MXF progress regression" \
  --summary "Updated progress to use true frame counts." \
  --prompt "User asked for accurate progress on MXF exports." \
  --actions "Adjusted estimateFrameCount routing in exporter and view model." \
  --decisions "Prefer measured frame counts over duration heuristics." \
  --questions "Confirm behavior for variable-frame-rate MXF corpus." \
  --tags "bugfix,mxf"
```

This creates a timestamped note in `Runs/`, appends it to `Run Log.md`, and links back to project anchor notes.

### 4) Retrieve context before answering

```bash
# search by topic
obmem search --project "ProjectName" --query "MXF fallback routing"

# inspect a key note
obmem read-note --path "Project Memory/project-name/Decisions.md"
```

### 5) Keep graph hygiene high

```bash
obmem audit --project "ProjectName"
```

This runs unresolved-link counts, orphan detection, dead-end detection, and backlink counts on the project home note.

Automatic behavior: `record-run` triggers auto-audit every N runs (default `5`).
Change cadence:

```bash
obmem set-audit-frequency --runs 5
```

Set `--runs 0` to disable auto-audit.

### 6) Health-check setup

```bash
obmem doctor
```

Validates Obsidian CLI availability, app reachability, workspace-to-vault mapping, and vault write access.

## Persistence Mode

Use this pattern to behave as "always-on" memory:

1. At first action in a session, run `show-vault`; ask user only if missing.
2. At task start, run `search` for key topic terms before proposing changes.
3. At task end, run `record-run` with summary + rationale.
4. Run `audit` periodically (or after major refactors).

### Hook Integration (Optional)

Claude Code hooks auto-search Obsidian before each prompt and auto-log after each stop.
See `claude-code/INSTALL.md` for setup instructions.

## Rules

1. Prefer wikilinks (`[[Note]]`) over plain text references.
2. Link every run note to at least: `[[<Project Home>]]`, `[[MOC]]`, and one topic/decision note.
3. Keep properties at the top of notes (`tags`, `created`, `updated`, `project`, `type`).
4. Use short, stable note titles; avoid duplicate names in the same vault.
5. Capture both outcome and rationale so later retrieval answers "what changed" and "why".

## Resources

- CLI entrypoint: `obmem` (installed via pipx)
- Hook scripts: `claude-code/hooks/`
- Reference patterns: `references/obsidian-cli-patterns.md`
