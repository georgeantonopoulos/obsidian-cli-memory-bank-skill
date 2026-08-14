---
name: obsidian-cli-memory-bank
description: Retrieve and maintain concise project memory through the obmem CLI and Claude Code hooks. Use to recall prior project decisions, record a meaningful outcome, compact noisy history, audit a selected project, or verify automatic memory hooks.
---

# Obsidian CLI Memory Bank

Use `obmem` as a small, project-scoped memory layer. Retrieve only enough context to act correctly, then record only information likely to matter in a future run.

## Default path

1. Resolve the vault and stable project identity.
2. Run one narrow active-memory search.
3. Read at most the 1–3 most relevant notes.
4. Do the task.
5. Record one concise sanitized run only in manual mode and only when the outcome is reusable.

Do not turn routine recall into a vault survey. Bootstrap, audit, compaction, archive search, and graph repair are exception paths.

## Hook mode

Claude Code may provide automatic memory through five hooks:

- `SessionStart`: validates vault connectivity.
- `UserPromptSubmit`: injects relevant search results before the response.
- `Stop`: records the completed turn.
- `PreCompact`: preserves a summary before context compression.
- `PostToolUse`: mirrors writes to memory files.

When hook output already provides the needed context, do not repeat `show-vault` or the same search. When the `Stop` hook is active, do not manually record the same task. Hooks are non-blocking; use the manual workflow only if hook output reports a failure or the exact context is still missing.

## Retrieval budget and filtering

- Run `show-vault` once per session or when the workspace changes.
- Run `list-projects` only when project identity is unknown or ambiguous.
- Start with one specific 3–8 word query; refine once only if irrelevant.
- Search active memory first; do not use `--include-archive` by default.
- Read at most 3 notes and stop when the needed fact or decision is clear.
- Never preload `Run Log`, all `Runs/`, all search hits, or raw transcripts.
- Do not run `audit`, `doctor`, or `compact-project` during ordinary recall.

Prefer results in this order:

1. `Current Memory.md`
2. Relevant `Topics/*.md`
3. `Decisions.md`, `Open Questions.md`, or a named reference note
4. A specific compaction note or recent run
5. `Archive/Runs/*` only for exact historical evidence

Filter out status chatter, retries, generic summaries, environment dumps, superseded detail, and unrelated facts. Prefer current decisions, constraints, known failures, verification, and unresolved questions.

```bash
obmem show-vault
obmem search --project "ProjectName" --query "specific subsystem decision"
obmem read-note --path "Project Memory/project-name/Current Memory.md"
```

If the first note answers the question, stop reading.

## Resolve identity safely

```bash
obmem show-vault
obmem list-projects
```

- Reuse an existing project slug that matches the repository or task.
- Keep the same `--project` value throughout the run.
- If no vault mapping exists, ask: `Which absolute vault path should I use for this project?`
- If several projects are plausible, ask instead of creating a duplicate.
- Use `--workspace "/path/to/project"` only for a different workspace.

For a genuinely new project only:

```bash
obmem init-project --project "ProjectName" --with-stub
```

## Record only durable outcomes

Record when a run adds a durable decision, non-obvious fix, reusable exact verification, or consequential open question. Skip simple lookups, status checks, retries, abandoned attempts, raw transcripts, and unchanged outcomes.

Keep prompt and summary to one sentence each; actions to 1–3 clauses; decisions/questions only when present; and tags to 2–5 specific terms.

```bash
obmem record-run \
  --project "ProjectName" \
  --title "Fix MXF frame-count routing" \
  --prompt "Correct inaccurate MXF export progress." \
  --summary "Progress now uses measured frame counts instead of duration estimates." \
  --actions "Updated exporter routing; ran the focused regression test." \
  --decisions "Prefer measured counts when available." \
  --questions "Validate variable-frame-rate MXF samples." \
  --tags "mxf,progress,bugfix"
```

`record-run` weaves bidirectional `## Related` edges to up to 5 lexical neighbors. Use descriptive titles and tags. If matching is weak, use `--auto-relate-query "specific terms"` or `--related "note-a,note-b"`; use `--no-auto-relate` when suggested links would be noise.

Never persist secrets, tokens, passwords, private access links, personal data, unredacted environment output, or copied transcripts.

## Exact evidence and maintenance

Search archives only when active memory lacks an exact command, error, date, or verification:

```bash
obmem search --project "ProjectName" --query "exact error or artifact" --include-archive
```

Read the smallest matching note and stop.

Compact only when active results are dominated by timestamped runs. Require a backup or clean recoverable Git state and preview a bounded batch:

```bash
obmem compact-project --project "ProjectName" --max-runs 25 --dry-run
obmem compact-project --project "ProjectName" --max-runs 25
```

Repair a specific graph relationship with `link-notes --dry-run`, then apply after reviewing it. Remove a wrong edge with `unlink-notes`, which drops both directions together. Never hand-edit only one side of a bidirectional `## Related` edge.

```bash
obmem unlink-notes --project "ProjectName" --from "run-note-stem" --to "Topic" --dry-run
```

When `record-run` reports an auto-related neighbor that is clearly off-topic, remove it rather than leaving it; a wrong edge costs more at recall time than a missing one.

```bash
obmem audit --project "ProjectName"
obmem doctor
```

Audit only while maintaining graph health or diagnosing retrieval. `obmem` is file-backed and does not require Obsidian desktop.

## Invariants

1. Prefer concise distilled memory over raw history.
2. Capture outcome and rationale, not narration.
3. Use short stable titles, specific tags, and file stems without `.md` for run wikilinks.
4. Keep note properties at the top.
5. Use `record-run` or `link-notes` to create bidirectional `## Related` edges, and `unlink-notes` to remove them.
6. Treat missing or ambiguous vault/project identity as a stop-and-ask condition.
7. Prefer no memory write over a low-signal or duplicate write.

Hook sources live in `claude-code/hooks/`; installation details live in `claude-code/INSTALL.md`.
