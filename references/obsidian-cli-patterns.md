# Obsidian CLI Patterns For Memory Bank Workflows

## Required setup

1. Use Obsidian `1.12+` early access and a Catalyst-enabled CLI registration.
2. Keep Obsidian app running while executing CLI commands.
3. Run commands from vault root (or pass `vault=<name>` as first parameter).

## Core command patterns used by this skill

```bash
# create note
obsidian create path="Project Memory/sequency/MOC.md" content="# MOC" silent

# append summary entry
obsidian append path="Project Memory/sequency/Run Log.md" content="- [[2026-02-14-fix-mxf]]"

# search project scope
obsidian search query="MXF fallback path:\"Project Memory/sequency\""

# inspect graph quality
obsidian unresolved counts verbose
obsidian orphans
obsidian deadends
obsidian backlinks path="Project Memory/sequency/Sequency Home.md" counts
```

## Note design rules

1. Use YAML properties for machine-readable metadata (`type`, `project`, `created`, `updated`, `tags`).
2. Use wikilinks for every cross-note reference.
3. Keep a central home note and MOC note for each project.
4. Log each run in a timestamped note under `Runs/`.
5. Append each run to a stable index note (`Run Log.md`) for fast retrieval.
