# Changelog

## Unreleased

- **The prompt hook no longer stalls a prompt for 20 s.** When the Jev request
  hung, the memory search waited out the hook's 20 s limit, so the prompt sat
  for 20 s and got no memory (4 of 422 recorded runs since 7 Nov, two of them
  on 27 Nov). urlopen's timeout covers each socket wait, not the request, so
  the Jev request now runs under a wall-clock limit (`OBMEM_JEV_TIMEOUT`,
  default 10 s; the prompt hook passes 1.5 s) and falls back to local ranking,
  reusing the shortlist instead of searching the vault again. The hook also
  cuts a search off at 5 s, other obmem calls at 3 s, and gives up entirely
  after 8 s. Measured on 10 real prompts with Jev made to hang: 20.3 s before,
  2.6 s after, memory still injected; with Jev answering normally, about
  1.4 s either way.

- **Native Antigravity plugin and lifecycle hooks.** Added `antigravity/` (`plugin.json`, `hooks.json`, `skills/obsidian-cli-memory-bank/SKILL.md`, `install.sh`, and `INSTALL.md`) and extended the shared hook scripts (`claude-code/hooks/`) to understand Antigravity's camelCase payloads, `transcript.jsonl` format, and JSON hook contracts (`SessionStart`, `PreInvocation`, and `Stop`) without duplicating hook logic or changing Claude Code behavior. `PreInvocation` deduplicates per user turn so memory search runs once per prompt across tool-call loops and surfaces a one-line inline `Memory:` notice via `metadata.user_markdown`; `Stop` auto-captures edited turns (`antigravity,auto-log`) on `NO_TOOL_CALL` completion and always returns `{"decision": "allow"}`. Shared hooks also fall back to `~/.local/bin/obmem` and Homebrew paths when GUI runtimes launch with a minimal `PATH`.

- **`obmem ask`: follow-up questions to memory.** When the first recall leaves
  a specific question open, `obmem ask --project X --question "..."` searches,
  reads the two best notes not already read (`--exclude`) around their
  matching lines, and ends with a status: `found`, `weak`, `nothing`, or
  `unchecked` when Jev did not run. Index pages (MOC, Run Log, compactions)
  are read last. The skill now says to follow up at most twice, then ask the
  user one multiple-choice question at a time and record the answer as a
  decision. Checked on 60 questions about past decisions in a real vault
  (45 worded directly, 15 vaguely), with Jev on: `found` showed the expected
  decision line 38 of 40 times on direct questions; on vague questions it said
  `weak` for 10 of 15, prompting a second search. Without Jev, word overlap
  alone said "found" wrongly 6 of 16 times, so it reports `unchecked`.

- **`obmem ask` lists later decisions.** A note can match the question yet hold a
  decision a later run replaced, and the replacing note often shares none of the
  question's words. When `ask` reads a run note that may be the answer, it now lists
  the next decisions after it in the project's `Decisions.md`, plus later ones on
  the same subject within a week (5 at most), so the agent can check none replaces it.
- **Wrapper prompts of your own tools are configurable.** Prompts that start
  with a label your own tooling adds (for example `[Nightly: ...]`) can be
  listed in `~/.config/obmem/wrapper-prompts.txt` (or the path in
  `OBMEM_WRAPPER_PROMPTS_FILE`), one regular expression per line, matched at
  the start of the prompt. Notes from those turns are titled from the reply.
  The file is empty by default; built-in patterns cover only Claude Code's own
  wrappers.

- **Search matches other forms of a word.** `sourcing` now finds notes that
  say `source`, `testers` finds `tester`, `decided` finds `decide`. Plain words
  of four or more letters share a root (one plural or tense ending removed);
  short words, all-caps acronyms (`AI`, `PR`, `MIT`), numbers and identifiers
  still match exactly, and a root only matches at the start of a word. On the
  local recall set (local ranker, same vault, back to back): plain search finds
  the decision for 37 of 45 questions instead of 33; the prompt hook shows it
  for 38 instead of 35, and 7 of 15 vaguely worded questions instead of 5.

- **Auto-saved notes are named after what was done.** When a turn was started
  by a message from another session or a subagent, a background task notice,
  the summary that continues a compacted session, or a labelled prompt sent by
  a tool (patterns listed in `~/.config/obmem/wrapper-prompts.txt`), the Stop hook now titles the note with the first sentence
  of the reply instead of the wrapper's opening words ("This session is being
  continued...", "Message from X: [Subagent hand-back]..."). 211 of the 328
  auto-saved notes in the live vault were started that way. Typed prompts keep
  their own title, and a reply too short to say anything ("(quiet)") keeps the
  old one. `<system-reminder>` blocks are dropped from the saved prompt.

- **Compaction notes keep the real summary.** The PreCompact hook used to save
  a "Pre-compaction snapshot: <project>" note holding only the last five
  prompts, cut short; 136 of the 1,261 run notes in the live vault were these,
  all with the same title. The SessionStart hook now saves, after compaction,
  the summary Claude Code itself wrote: the request, errors and fixes, findings,
  pending work and current work (about 3,000 characters; the user's own
  messages and the concept and file lists are left out). The note is titled
  "Compaction: <what the session was doing>". The note is saved by a detached
  background process, so session start does not wait for it (0.2 s in a real
  run). Each compaction gets one note: PreCompact marks the session and claims
  the summary already on disk, so an earlier compaction's summary is never
  saved again, and a second start after the same compaction saves nothing. If
  no new summary appears within 20 seconds, the recent prompts are saved as
  before.

- **No more empty hub notes.** New projects no longer get Architecture,
  Roadmap, Debugging Notes and Release Notes: nothing ever wrote to them, and
  409 of the 424 in the live vault's 106 projects still held only the
  template. `obmem prune-hubs` lists the template-only ones and `--apply`
  deletes them and the bare link lines in Home, MOC and sibling hubs. A hub
  with writing in it, Related links, or a link to it in a sentence is kept. On
  a copy of the live vault: 409 files gone, 0 broken links before and after,
  and a second run finds nothing.

- **Fewer Jev calls.** The prompt hook no longer searches memory for messages
  that come from tools or other sessions instead of the user (background task
  notices, messages from another Claude session, the summary that continues a
  compacted session); `skip:<regex>` lines in the query-ignore file add more.
  Jev now judges the 10 best local matches of each search instead of up to
  30, so a prompt's two searches send 20 notes instead of 60.

- **Prompts can recall another project's decision.** The prompt hook also
  searches every project. When the top note of that search belongs to another
  project, that one note is added (labelled as from another project, shorter
  excerpt). Otherwise the output is unchanged. The two searches run side by
  side; with Jev ranking on, each prompt makes two Jev calls instead of one.

- **`obmem search --all-projects`** searches every project's memory instead of
  one. `search` now needs either `--project` or `--all-projects`.

- **Faster local search.** Notes that contain none of the keywords are skipped
  before scoring, and `Archive/` folders are no longer walked when archive is
  excluded. Results are unchanged.

- **Excerpts show the lines that match.** The prompt hook pastes in the top
  notes; for a note longer than the excerpt (a decision register, a topic), it
  now shows the note's title and the lines around the one that holds most of
  the search keywords, instead of only the opening. Excerpt size is unchanged.

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
