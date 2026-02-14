---
name: obsidian-cli-memory-bank
description: Build and maintain project-specific Obsidian knowledge bases through Obsidian CLI. Use when Codex needs to (1) ask once for a vault and persist it for a workspace, (2) capture prompt/run context as structured Markdown notes, (3) auto-link notes with wikilinks for strong backlink coverage, (4) retrieve context quickly via Obsidian CLI search/read commands, or (5) audit graph hygiene with unresolved/orphan/dead-end link checks.
---

# Obsidian Cli Memory Bank

## Overview

Use this skill to maintain a per-project "memory bank" inside Obsidian with consistent note structure, dense wikilinking, and CLI-first retrieval.
Persist the vault path once, then bootstrap/update project notes on every relevant run.

## Workflow

From any workspace, run helper commands from this skill folder first:

```bash
cd "$CODEX_HOME/skills/obsidian-cli-memory-bank"
```

### 1) Resolve vault first

Run:

```bash
python3 scripts/obsidian_memory.py show-vault
```

If no vault is set for the current workspace:

1. Ask exactly one question: `Which absolute vault path should I use for this project?`
2. Save it:

```bash
python3 scripts/obsidian_memory.py set-vault --vault-path "/absolute/path/to/vault"
```

Use `--workspace "/path/to/project"` when setting or resolving a different workspace than the current directory.

### 2) Bootstrap project memory structure

Create core notes once per project:

```bash
python3 scripts/obsidian_memory.py bootstrap --project "Sequency"
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
python3 scripts/obsidian_memory.py record-run \
  --project "Sequency" \
  --title "Fix MXF progress regression" \
  --summary "Updated progress to use true frame counts." \
  --prompt "User asked for accurate progress on MXF exports." \
  --actions "Adjusted estimateFrameCount routing in exporter and view model." \
  --decisions "Prefer measured frame counts over duration heuristics." \
  --questions "Confirm behavior for variable-frame-rate MXF corpus." \
  --tags "swift,mxf,bugfix"
```

This creates a timestamped note in `Runs/`, appends it to `Run Log.md`, and links back to project anchor notes.

### 4) Retrieve context before answering

Use CLI retrieval first:

```bash
# search by topic
python3 scripts/obsidian_memory.py search --project "Sequency" --query "MXF fallback routing"

# inspect a key note
python3 scripts/obsidian_memory.py read-note \
  --project "Sequency" \
  --path "Project Memory/sequency/Decisions.md"
```

### 5) Keep graph hygiene high

Run periodic audits:

```bash
python3 scripts/obsidian_memory.py audit --project "Sequency"
```

This runs:

- `obsidian unresolved counts verbose`
- `obsidian orphans`
- `obsidian deadends`
- `obsidian backlinks path="<project-home-note>" counts`

## Rules

1. Prefer wikilinks (`[[Note]]`) over plain text references.
2. Link every run note to at least: `[[<Project Home>]]`, `[[MOC]]`, and one topic/decision note.
3. Keep properties at the top of notes (`tags`, `created`, `updated`, `project`, `type`).
4. Use short, stable note titles; avoid duplicate names in the same vault.
5. Capture both outcome and rationale so later retrieval answers "what changed" and "why".

## Resources

- Script entrypoint: `scripts/obsidian_memory.py`
- Reference patterns: `references/obsidian-cli-patterns.md`
