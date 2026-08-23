---
name: obsidian-cli-memory-bank
description: Retrieve and maintain concise project memory through the obmem CLI. Use to recall prior project decisions, record a meaningful outcome, compact noisy history, or audit a selected project's memory graph.
---

# Obsidian CLI Memory Bank

Use `obmem` as a small, project-scoped memory layer. Retrieve only enough context to act correctly, then record only information likely to matter in a future run.

## Default path

1. Resolve the vault and stable project identity.
2. Run one narrow active-memory search.
3. Read at most the 1–3 most relevant notes.
4. Do the task.
5. In manual mode, record one concise sanitized run if the outcome is reusable.

Do not turn routine recall into a vault survey. Bootstrap, audit, compaction, archive search, and graph repair are exception paths, not session-start requirements.

## Retrieval budget and filtering

Default limits:

- Run `show-vault` once per session or when the workspace changes.
- Run `list-projects` only when the project identity is unknown or ambiguous.
- Start with one specific 3–8 word query. Refine once only if results are irrelevant.
- Search active memory first; do not use `--include-archive` by default.
- Read at most 3 notes and stop as soon as the needed decision, fact, or prior result is clear.
- Never preload `Run Log`, all `Runs/`, all search hits, or raw transcripts.
- Do not run `audit`, `doctor`, or `compact-project` during ordinary recall.

Prefer results in this order:

1. `Current Memory.md`
2. Relevant `Topics/*.md`
3. `Decisions.md`, `Open Questions.md`, or a named architecture/reference note
4. A specific compaction note or recent run
5. `Archive/Runs/*` only when exact historical evidence is required

Filter out status chatter, repeated retries, generic summaries, environment dumps, superseded implementation detail, and facts unrelated to the current request. Prefer current decisions, constraints, known failures, exact verification, and unresolved questions.

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
- Keep the same `--project` value for every command in the run.
- If no vault mapping exists, ask exactly: `Which absolute vault path should I use for this project?`
- If several projects are plausible, ask one short question instead of creating a duplicate.
- Use `--workspace "/path/to/project"` only when operating on a workspace other than the current directory.

For a genuinely new project only:

```bash
obmem init-project --project "ProjectName" --with-stub
```

## Record only durable outcomes

Manual mode records once after a meaningful task. Hook mode already records turns; do not duplicate it.

Record when the run adds at least one of:

- a durable decision or constraint;
- a non-obvious fix, cause, or failure mode;
- an exact command, artifact, path, version, or verification result worth reusing;
- an unresolved question that affects later work.

Skip greetings, status checks, simple lookups, abandoned attempts, repeated retries, raw transcripts, and outcomes already captured unchanged.

Keep each field short: prompt and summary 1 sentence each; actions 1–3 concrete clauses; decisions/questions only when present; 2–5 specific tags. Preserve exact details only when they improve future execution.

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

`record-run` automatically links hubs and weaves bidirectional `## Related` edges to up to 5 lexical neighbors. Check its output for `no neighbors found`, `search failed`, or `could not resolve`. Use a descriptive title and tags; if lexical matching is weak, use `--auto-relate-query "specific terms"` or `--related "note-a,note-b"`. Use `--no-auto-relate` for pioneer topics or when suggested links would be noise.

Never persist secrets, tokens, passwords, private access links, personal data, unredacted environment output, or a copied transcript.

## Exact evidence and archive fallback

Use archive search only when active memory lacks an exact command, error, date, or verification detail:

```bash
obmem search --project "ProjectName" --query "exact error or artifact" --include-archive
```

Read the smallest matching source note, extract the needed fact, and stop. Treat archived runs as cold evidence, not normal context.

## Maintenance paths

### Compact noisy history

Compact when active search is dominated by timestamped run notes. Because compaction moves notes and prunes indexes, require a backup or clean recoverable Git state, then preview a bounded batch:

```bash
obmem compact-project --project "ProjectName" --max-runs 25 --dry-run
obmem compact-project --project "ProjectName" --max-runs 25
obmem search --project "ProjectName" --query "representative topic"
obmem search --project "ProjectName" --query "representative topic" --include-archive
```

The result promotes `Current Memory.md` and `Topics/*.md` while retaining raw evidence under `Archive/Runs/`. Use `--include-archive` on compaction only to re-distill archived evidence after rules improve. Use `--no-archive` only when deliberately leaving raw runs active.

Each bounded batch automatically includes previously archived runs in the distilled result, so a later 25-note pass cannot erase earlier hot memory. `--max-runs` limits only the new active notes; `--include-archive` forces a refresh when no new runs exist. Active distilled notes filter transcript wrappers, instruction boilerplate, credentials, private endpoints, email addresses, and phone numbers while leaving raw archived evidence untouched.

### Repair graph links

`## Related` edges must be bidirectional. Never hand-edit only one side. For a specific missing relationship:

```bash
obmem link-notes \
  --project "ProjectName" \
  --from "source-note-stem" \
  --to "target-note-stem" \
  --reason "shared subsystem" \
  --dry-run
```

Remove `--dry-run` after reviewing the target. Prefer 2–5 genuine peer links over broad hub linking; zero is valid for a new topic.

### Audit or diagnose

```bash
obmem audit --project "ProjectName"
obmem doctor
```

Audit only the selected project and only when maintaining graph health or investigating retrieval problems. Orphans and dead ends are signals, not a requirement to link every note. `doctor` checks mapping, cadence, optional CLI availability, and write access; `obmem` itself is file-backed and does not require Obsidian desktop.

## Invariants

1. Prefer concise distilled memory over raw history.
2. Capture outcome and rationale, not narration.
3. Use short stable titles, specific tags, and file stems without `.md` for run-note wikilinks.
4. Keep note properties at the top.
5. Use `record-run` or `link-notes` to create bidirectional `## Related` edges, and `unlink-notes` to remove them.
6. Preserve exact commands, paths, errors, decisions, and verification only when they are reusable.
7. Treat missing or ambiguous vault/project identity as a stop-and-ask condition.
8. Prefer no memory write over a low-signal memory write.
