# Memory maintenance

Load only for requested compaction, graph repair, or diagnosis.

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
