---
name: obsidian-cli-memory-bank
description: Build and maintain project-specific Obsidian knowledge bases via the obmem CLI. This skill should be used when an agent needs to (1) persist a vault mapping for a workspace, (2) capture prompt/run context as structured Markdown notes, (3) weave notes into a densely interconnected brain via bidirectional wikilinks (not just hub-and-spoke), (4) retrieve context via search/read commands, or (5) audit graph hygiene with unresolved/orphan/dead-end link checks.
---

# Obsidian CLI Memory Bank

## Overview

Use this skill to maintain a per-project "memory bank" inside Obsidian shaped as an **interconnected brain**, not a star graph.
Every note links to its neighbors in both directions, so navigation works by association (run → related run → decision → question) rather than by always routing through `Project Home`.
Persist the vault path once per workspace, then bootstrap, record, and weave notes together on every relevant run.

### Graph Shape: Brain, Not Star

`record-run` links every new note up to hub notes (`Project Home`, `MOC`, `Run Log`, `Decisions`, `Open Questions`). On its own that would produce a star graph. To turn the star into a brain, `record-run` **also runs an automatic bidirectional weaving pass** by default:

1. Derives a search query from the run's title + tags (or accepts `--auto-relate-query`).
2. Searches the project for semantically related prior notes.
3. Writes a `## Related` section on the new run note linking to each neighbor.
4. Appends a reverse wikilink into each neighbor's own `## Related` section.

Both directions are written to disk in the same invocation. This is a **CLI feature**, not a post-step the agent performs — once the `obmem record-run` call returns successfully, the graph is already interconnected.

Obsidian's backlink pane is a view, not a data source — CLI retrieval (`obmem search`, grep) only sees explicit wikilinks, which is why the reverse edge has to be written on disk.

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

Auto-relate runs by default. It derives a search query from `--title` + `--tags`, searches the project for prior notes, and writes bidirectional `## Related` links to the top 5 hits (excluding hub notes). The command output shows each edge it writes, e.g.:

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

### 3b) Link existing notes retroactively

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

Use this pattern to behave as "always-on" interconnected memory:

1. At first action in a session, run `show-vault`; ask the user only if missing.
2. At task start, run `search` for the topic to load prior context into your own reasoning. (You do **not** need to pass those results to `record-run` — auto-relate will re-derive them.)
3. At task end, run `record-run` with a descriptive `--title` and relevant `--tags`. Auto-relate writes bidirectional edges to the top neighbors automatically; no post-step is required.
4. If the auto-derived query misses the real topic (generic title, unusual symbol), re-run with `--auto-relate-query "specific keywords"` or append explicit `--related` targets.
5. Run `audit` periodically — rising orphan or dead-end counts signal that a particular run's title/tags are too generic for auto-relate, or that `--no-auto-relate` was used without `--related`.

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
2. **Every edge is bidirectional.** `record-run` and `link-notes` both enforce this — every wikilink they write on note A is paired with a reverse link on note B. Never bypass this by hand-editing one side of an edge.
3. Give run notes descriptive `--title` and specific `--tags` so auto-relate has enough lexical signal to find real neighbors. Generic titles ("Bugfix", "Update", "Follow-up") produce empty neighborhoods.
4. Prefer peer-to-peer edges (run ↔ run, run ↔ decision, run ↔ question) over additional edges to `Project Home` / `MOC` / `Run Log`; hubs are already saturated by the header block `record-run` writes.
5. Keep properties at the top of notes (`tags`, `created`, `updated`, `project`, `type`).
6. Use short, stable note titles; avoid duplicate names in the same vault. Use **file stems** (no `.md`) as wikilink targets for run notes.
7. Capture both outcome and rationale so later retrieval answers "what changed" and "why".
8. Treat the `audit` orphan/dead-end counts as a bidirectionality health check — rising numbers mean auto-relate is firing on too-generic titles or is being disabled.

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
