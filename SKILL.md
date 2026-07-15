---
name: obsidian-cli-memory-bank
description: Build and maintain project-specific Obsidian knowledge bases via the obmem CLI. Use when an agent needs to persist a vault mapping, reuse a stable project identity, retrieve prior context, capture a meaningful run, compact noisy history, or audit project graph hygiene.
---

# Obsidian CLI Memory Bank

## Overview

Use this skill to maintain a per-project memory bank inside Obsidian. The normal operator path is:

1. Resolve the vault and reuse the correct project identity.
2. Search active memory before acting.
3. Complete the task.
4. Record one sanitized, meaningful run.
5. Compact safely when raw run history becomes noisy.
6. Audit only the selected project.

The graph should support associative navigation (run → related run → decision → question) without making raw run notes the primary retrieval surface.

### Graph Shape: Brain, Not Star

`record-run` links every new note up to hub notes (`Project Home`, `MOC`, `Run Log`, `Decisions`, `Open Questions`). On its own that would produce a star graph. To turn the star into a brain, `record-run` **also runs an automatic bidirectional weaving pass** by default:

1. Derives a search query from the run's title + tags (or accepts `--auto-relate-query`).
2. Searches the project for lexically related prior notes.
3. Writes a `## Related` section on the new run note linking to each neighbor.
4. Appends a reverse wikilink into each neighbor's own `## Related` section.

Both `## Related` directions are written in the same invocation. Check command output: `no neighbors found`, `search failed`, or `could not resolve` means the run was recorded but some lateral edges were not created.

Obsidian's backlink pane is a view, not a data source — CLI retrieval (`obmem search`, grep) only sees explicit wikilinks, which is why the reverse edge has to be written on disk.

## Prerequisites

- `obmem` CLI installed via pipx (`pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git`)
- Write access to the configured Obsidian vault folder
- Optional: an Obsidian CLI in PATH if you want external app conveniences

`obmem` uses direct file-backed vault operations for its own create, append, read, search, and audit
commands. Obsidian desktop does not need to be running, and the old `obsidian` app IPC bridge is no
longer required for normal memory-bank work.

Obsidian desktop 1.12+ may bundle and register an official CLI. A separately installed Homebrew or third-party `obsidian-cli` can coexist and may appear earlier on `PATH`. Updating the desktop app does not update `obmem` or a separately installed CLI. The memory-bank workflow remains file-backed and does not depend on either CLI.

## Operating modes

- **Manual mode:** search at task start and call `record-run` once after a meaningful task completes.
- **Hook mode:** let the runtime hook record turns; do not manually record the same task again.

Do not record status pings, empty turns, repeated retries, or raw transcripts when a short outcome-and-rationale summary is enough.

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

### 2) Resolve project identity

List existing projects before choosing a name:

```bash
obmem list-projects
```

- Reuse an existing project slug when it matches the current repository or task.
- Derive a new name from the repository root only when no suitable project exists.
- If multiple existing projects are plausible, ask one short question instead of creating another folder.
- Keep the same `--project` value for search, record, compact, link, and audit commands.

### 3) Bootstrap project memory structure

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

### 4) Record each meaningful run

`record-run` creates a timestamped note in `Runs/`, appends it to `Run Log.md`, links up to the hubs, **and automatically weaves bidirectional `## Related` edges to the most relevant prior notes**. Default invocation:

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

Auto-relate runs by default. It derives a lexical search query from `--title` + `--tags`, searches the project for prior notes, and writes bidirectional `## Related` links to the top 5 hits (excluding hub notes). The command output shows each edge it writes, e.g.:

```
Recorded run note: Project Memory/sequency/Runs/2026-04-11-1530-fix-mxf-progress-regression.md
auto-relate: weaving 3 neighbor(s)
  → linked:.../2026-04-11-1530-fix-mxf-progress-regression.md ← [[2026-03-29-1312-fix-video-duration-detection-and-sourceframerate-wiring]]
  ← linked:.../2026-03-29-1312-fix-video-duration-detection-and-sourceframerate-wiring.md ← [[2026-04-11-1530-fix-mxf-progress-regression]]
  ...
```

Idempotent: if a given link already exists on a note, the CLI skips it instead of duplicating the entry.

#### Auto-relate flags

| Flag | Purpose |
|------|---------|
| `--related "a,b,c"` | Explicit neighbor list — file stems, short names (`Decisions`, `Architecture`), wikilinks (`[[note]]`), or vault-relative paths. Takes precedence; auto-discovered neighbors top up the list up to `--auto-relate-limit`. |
| `--auto-relate-query "keywords"` | Override the default query derived from title + tags. Useful when the title is generic ("Bugfix") but the actual topic is specific ("arri mxf audio fallback"). |
| `--auto-relate-limit N` | Cap the total number of bidirectional neighbor links (default `5`). |
| `--no-auto-relate` | Disable automatic discovery entirely; only `--related` edges are woven. Use for initial seed notes with no relevant history. |

Example with explicit neighbors:

```bash
obmem record-run \
  --project "ProjectName" \
  --title "Fix MXF progress regression" \
  --related "2026-03-29-1312-fix-video-duration-detection-and-sourceframerate-wiring,Decisions,Architecture" \
  --prompt "..." --summary "..." --actions "..."
```

**Rules of thumb for picking explicit neighbors:**

- Link **runs to runs** when they touch the same subsystem, symbol, or bug class — this is the primary lateral edge that turns the star into a brain.
- Link **runs to decisions** when the run enacts, revisits, or contradicts a recorded decision.
- Link **runs to questions** when the run answers or raises a question.
- Aim for 2–5 neighbor edges per run. Zero is usually fine for pioneer topics; more than 5 usually means the topic is too coarse.

#### Update hub indexes periodically

When several lateral edges form a cluster around one topic (e.g. three runs now discuss "mxf progress"), add them under a topic heading inside `MOC.md` so the cluster is discoverable from the hub as well as from each run. The CLI does not do this automatically — it is the one place where hub curation remains a manual call.

### 4b) Link existing notes retroactively

To weave edges between notes that already exist (retrofit a star-shaped vault, connect older runs, attach a run to a decision after the fact):

```bash
obmem link-notes \
  --project "ProjectName" \
  --from "2026-04-11-1530-fix-mxf-progress-regression" \
  --to "2026-03-29-1312-fix-video-duration-detection-and-sourceframerate-wiring,Decisions" \
  --reason "frame-count work thread"
```

- `--from` accepts the same reference forms as `--related` (stem, short name, wikilink, or vault-relative path).
- `--to` accepts a comma-separated list; each target gets a bidirectional edge.
- `--reason` is optional and is appended to each `## Related` entry on both sides.
- Idempotent: rerunning the same command is a no-op.
- Supports `--dry-run` to preview edits.

Use `link-notes` inside a retrofitting loop: `obmem audit` → identify orphans/dead-ends → run `obmem search` to find candidates → `obmem link-notes` to weave.

### 4c) Compact noisy run history into useful memory

When a project has many run notes, stop treating `Runs/` as the primary memory surface. Compaction moves notes and prunes indexes, so use this safety sequence:

```bash
# 1. Ensure the vault has a backup or a clean, recoverable Git state.
# 2. Preview a bounded batch.
obmem compact-project --project "ProjectName" --max-runs 25 --dry-run

# 3. Apply the same bounded batch after reviewing the plan.
obmem compact-project --project "ProjectName" --max-runs 25

# 4. Verify active retrieval and archived evidence.
obmem search --project "ProjectName" --query "representative topic"
obmem search --project "ProjectName" --query "representative topic" --include-archive
```

This creates or updates:

- `Project Memory/<project>/Current Memory.md`
- `Project Memory/<project>/Topics/*.md`
- `Project Memory/<project>/Compactions/<timestamp>-compact-<project>.md`
- `Project Memory/<project>/Archive/Runs/*.md`

Compaction keeps raw run notes as evidence, but moves them out of active `Runs/`, marks them `status: "compacted"`, removes old graph-heavy `## Related` links and hub breadcrumbs, and gives each archived run sparse links to the compaction/topic notes that distilled it. Hub indexes are pruned so the active graph starts from `Current Memory` and topic notes instead of hundreds of run nodes.

Use `--no-archive` only when you want to preview distilled notes while leaving active run nodes in place.
Use `--include-archive` to re-distill already archived evidence after improving compaction rules:

```bash
obmem compact-project --project "ProjectName" --include-archive
```

### 5) Retrieve context before answering

```bash
# search by topic
obmem search --project "ProjectName" --query "MXF fallback routing"

# include archived source evidence only when needed
obmem search --project "ProjectName" --query "MXF fallback routing" --include-archive

# inspect a key note
obmem read-note --path "Project Memory/project-name/Decisions.md"
```

### 6) Keep graph hygiene high

```bash
obmem audit --project "ProjectName"
```

This runs project-scoped unresolved-link counts, orphan detection, and dead-end detection, plus a backlink count for the selected project home note. If the project does not exist, the command stops and directs you to `obmem list-projects` instead of reporting a misleading clean audit.

Automatic behavior: `record-run` triggers auto-audit every N runs (default `5`).
Search now skips `Archive/` by default and ranks compacted notes (`Current Memory`, `Topics`, `Compactions`, Decisions, Questions, Architecture) before raw `Runs/`. Use `--include-archive` when you need to search archived source evidence. Run `compact-project` whenever search starts returning too many timestamped execution notes.
Change cadence:

```bash
obmem set-audit-frequency --runs 5
```

Set `--runs 0` to disable auto-audit.

### 7) Health-check setup

```bash
obmem doctor
```

Reports optional CLI availability, workspace-to-vault mapping, audit cadence, and vault write access. It does not require Obsidian desktop to be running.

## Persistence Mode

Use this pattern to behave as "always-on" interconnected memory:

1. At first action in a session, run `show-vault`; ask the user only if missing.
2. Run `list-projects` and reuse the stable project identity.
3. At task start, run `search` for the topic to load prior context into your reasoning.
4. In manual mode, run `record-run` once at task end with a descriptive title, specific tags, and a sanitized summary. In hook mode, do not duplicate the hook record.
5. Inspect auto-relate output. If lexical discovery misses the real topic, use `--auto-relate-query "specific keywords"` or explicit `--related` targets.
6. Run project-scoped `audit` periodically. Compact only after a backup or clean Git checkpoint, a dry-run, and post-search verification.

### Hook Integration (Optional)

Claude Code hooks provide five automatic integration points:

| Hook | Event | Purpose |
|------|-------|---------|
| `obsidian_sessionstart_hook.py` | `SessionStart` | Validate vault connectivity at session start |
| `obsidian_preprompt_hook.py` | `UserPromptSubmit` | Search Obsidian for relevant notes before each response |
| `obsidian_poststop_hook.py` | `Stop` | Log a structured run note after each agent stop |
| `obsidian_precompact_hook.py` | `PreCompact` | Persist session context to Obsidian before context compaction |
| `obsidian_memory_sync_hook.py` | `PostToolUse` | Mirror MEMORY.md writes to Obsidian vault |

The **PreCompact** hook captures a transcript summary as an Obsidian note before context compression, so project knowledge survives context boundaries.

The **PostToolUse** hook watches for `Write`/`Edit` calls targeting `*/memory/*` or `*MEMORY.md` paths, syncing auto-memory to Obsidian.

## Rules

1. Prefer wikilinks (`[[Note]]`) over plain text references.
2. **Every `## Related` edge created by `record-run` or `link-notes` is bidirectional.** Ordinary wikilinks and hub breadcrumbs are not covered by this guarantee. Never hand-edit only one side of a `## Related` edge.
3. Give run notes descriptive `--title` and specific `--tags` so auto-relate has enough lexical signal to find real neighbors. Generic titles ("Bugfix", "Update", "Follow-up") produce empty neighborhoods.
4. Prefer peer-to-peer edges (run ↔ run, run ↔ decision, run ↔ question) over additional edges to `Project Home` / `MOC` / `Run Log`; hubs are already saturated by the header block `record-run` writes.
5. Keep properties at the top of notes (`tags`, `created`, `updated`, `project`, `type`).
6. Use short, stable note titles; avoid duplicate names in the same vault. Use **file stems** (no `.md`) as wikilink targets for run notes.
7. Capture both outcome and rationale so later retrieval answers "what changed" and "why".
8. Treat project-scoped orphan/dead-end counts as a graph-health signal, not proof that every note needs more links.
9. Never persist API keys, tokens, passwords, access links, private personal details, or unredacted environment output. Prefer the minimum sanitized context needed for future retrieval.
10. Preserve exact commands, paths, errors, decisions, and verification results when they are useful, but summarize raw transcripts rather than copying them wholesale.

### Retrofitting an existing star graph

If the vault already contains star-shaped run notes without lateral edges, convert them with `obmem link-notes`:

1. Run `obmem audit --project "ProjectName"` to list orphans and dead-ends.
2. For each orphan, run `obmem search --project "ProjectName" --query "<keywords>"` to find candidates (use terms from the note's title/summary).
3. Weave bidirectional edges with one CLI call:

    ```bash
    obmem link-notes \
      --project "ProjectName" \
      --from "<orphan-stem>" \
      --to "<candidate1-stem>,<candidate2-stem>" \
      --reason "<thread or subsystem>"
    ```

4. Re-audit; repeat until orphan and dead-end counts stabilize near zero.

Retrofit one note (or small batch) at a time rather than scripting a bulk pass — each weave is a judgment call about whether two notes are genuinely related, and bulk automation tends to create noisy edges that poison retrieval. Use `--dry-run` when in doubt.
