# Changelog

## Unreleased

- **Optional capture ignore list** (`~/.config/obmem/capture-ignore.txt`): a
  turn whose only edits are to listed files (for example a running notebook)
  no longer gets an automatic run note, since the file is already the record.

## 0.2.0

Claude Code hooks only; the `obmem` CLI and vault format are unchanged.

### Better recall

- **Prompts find the note that answers them.** Search results keep their
  ranked order; previously a raw run note that held the answer was pushed
  behind summary pages (MOC, Decisions) that only listed it in one line. Now
  only `MOC`, `Run Log`, `Compactions/` and `Archive/` go last.
- **Versions, prices and error codes are searched.** `2.4.1`, `$4.99`, `404`
  are kept as keywords and ranked first (before, `$4.99` became `99` and
  `2.4.1` was dropped). Up to five keywords are searched instead of four.
- **Relayed messages search their topic.** When Claude Code delivers a message
  from another session or a background-task notice, its wrapper and delivery
  words (SendMessage, notification, session) are no longer used as keywords.
  Typed prompts keep those words, since there they are usually the subject.
- **Optional ignore list** (`~/.config/obmem/query-ignore.txt`) for words that
  never help, such as names of people or agents you often mention.

### Cleaner automatic run notes

- **Each auto note matches the turn it came from.** A turn started by a
  background-task notice or a message from another session is now its own
  turn; before, its reply was filed under the previous typed prompt and that
  prompt's file edits were logged again. A notice that arrives mid-turn stays
  part of that turn.
- **No duplicates.** If the turn already ran `obmem record-run` successfully,
  no auto note is added, and each turn is logged at most once.
- Hooks never fail the session on an unexpected transcript line.

### Updating

- `pipx upgrade obsidian-cli-memory-bank` (or reinstall from git).
- Copied hooks: copy all six `claude-code/hooks/*.py` again. Symlinked hooks
  need nothing. No `settings.json` change and no vault migration.
- New state: `~/.cache/obmem/stop-hook-seen/` (one tiny file per session,
  pruned after 14 days; override with `OBMEM_STOP_STATE`).

## 0.1.0

- First release.
