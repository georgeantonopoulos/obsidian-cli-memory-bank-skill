# Changelog

## 0.2.0

Claude Code hooks only; the `obmem` CLI and vault format are unchanged.

- **Stop hook pairs each auto note with the right turn.** Messages from other
  sessions, background task notices and idle notices now start a turn when the
  session was idle, so a reply is no longer filed under an earlier typed prompt
  and earlier edits are no longer logged again. A message that lands mid-turn
  stays part of that turn.
- **No duplicate auto notes.** A turn whose `obmem record-run` succeeded is not
  auto-logged, and each turn is logged at most once per session
  (`~/.cache/obmem/stop-hook-seen/`, override with `OBMEM_STOP_STATE`).
- **Prompt search looks for the topic.** Message wrappers and messaging words
  are dropped, prices and versions (`$0`, `1.5`) are kept and ranked first,
  and up to five keywords are searched.
- **Optional ignore list** at `~/.config/obmem/query-ignore.txt`
  (`OBMEM_QUERY_IGNORE_FILE`) for names and words the prompt search should skip.
- **Search order kept.** Run notes are no longer pushed behind summary pages;
  only `MOC`, `Run Log`, `Compactions/` and `Archive/` go last.
- Hooks fail open on unexpected transcript shapes.

### Updating

- `pipx upgrade obsidian-cli-memory-bank` (or reinstall from git).
- Copied hooks: copy all six `claude-code/hooks/*.py` again. Symlinked hooks
  need nothing. No `settings.json` change and no vault migration.

## 0.1.0

- First release.
