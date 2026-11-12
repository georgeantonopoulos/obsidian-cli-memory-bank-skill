# Claude Code Integration

## 1) Install the CLI

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
```

Verify:

```bash
obmem --help
obmem doctor
```

## 2) Install the skill

Copy or symlink the Claude Code skill into your skills directory:

```bash
mkdir -p ~/.claude/skills/obsidian-cli-memory-bank
cp claude-code/SKILL.md ~/.claude/skills/obsidian-cli-memory-bank/SKILL.md
```

Or symlink for auto-updates:

```bash
mkdir -p ~/.claude/skills/obsidian-cli-memory-bank
ln -sf "$(pwd)/claude-code/SKILL.md" ~/.claude/skills/obsidian-cli-memory-bank/SKILL.md
```

## 3) Install hooks (optional)

Copy the hook scripts:

```bash
mkdir -p ~/.claude/hooks
cp claude-code/hooks/obsidian_preprompt_hook.py ~/.claude/hooks/
cp claude-code/hooks/obsidian_poststop_hook.py ~/.claude/hooks/
cp claude-code/hooks/obsidian_precompact_hook.py ~/.claude/hooks/
cp claude-code/hooks/obsidian_sessionstart_hook.py ~/.claude/hooks/
cp claude-code/hooks/obsidian_memory_sync_hook.py ~/.claude/hooks/
cp claude-code/hooks/obsidian_hook_common.py ~/.claude/hooks/   # shared helpers, required
chmod +x ~/.claude/hooks/obsidian_*.py
```

Add hook entries to `~/.claude/settings.json` under the `"hooks"` key:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/obsidian_sessionstart_hook.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/obsidian_preprompt_hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/obsidian_poststop_hook.py"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/obsidian_precompact_hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/obsidian_memory_sync_hook.py"
          }
        ]
      }
    ]
  }
}
```

If you already have hooks configured for these events, append the new hook group to the existing array.

### What the hooks do

- **SessionStart** (session-start): Validates vault connectivity at session start. Surfaces warnings early if Obsidian is unreachable or the vault is misconfigured.
- **UserPromptSubmit** (pre-prompt): Searches Obsidian for notes relevant to your prompt before Claude answers. Surfaces prior context automatically.
- **Stop** (post-stop): Logs a run note with the prompt (read from the transcript), the final reply, and the files changed. By default only turns that edited files are logged; set `OBMEM_STOP_LOG=all` to log every turn or `OBMEM_STOP_LOG=off` to disable. A turn starts on a typed prompt and also on a message from another session, a background task notice or an idle notice that arrives while the session is idle, so the note pairs each reply with what it answered and lists only that turn's edits. A turn whose `obmem record-run` succeeded is not logged again, and each turn is logged at most once (per-session state in `~/.cache/obmem/stop-hook-seen/`, override with `OBMEM_STOP_STATE`).
- **PreCompact** (pre-compaction): Saves the recent prompts to Obsidian before context compression. Prevents knowledge loss when conversations hit context limits.
- **PostToolUse** (post-write/edit): Mirrors Claude Code auto-memory writes (`~/.claude/projects/*/memory/*.md`) to the vault.

All hooks silently no-op when no vault is mapped for the current workspace.

- **Project identity**: hooks use the directory Claude was launched in (`CLAUDE_PROJECT_DIR`, else the git root), so `cd`-ing into a subfolder does not file notes under another project.
- **Secrets**: API keys, bearer tokens, `KEY=value` secrets and long opaque tokens are redacted before any search query, Jev request, or run note.
- **Opt out**: `OBMEM_HOOKS=off` disables all hooks; an empty `.obmem-off` file in a project root disables them for that project.
- **Prompt search**: skips short acknowledgements, drops message wrappers (another session's message, `[Label: ...]` prefixes, XML-like tags) and messaging words (SendMessage, notification, session), ranks prices, versions and codes (`$0`, `1.5`, `404`) first, then proper nouns and `identifiers`, then filler words, and searches up to five of them. With the Jev ranker enabled it passes the redacted prompt as `--intent`; if no note clears the Jev relevance threshold (`OBMEM_JEV_MIN`, default 0.50) the hook prints nothing. The search's own order is kept except that index pages (`MOC`, `Run Log`, `Compactions/`, `Archive/`) go last; copies of the agent's own memory files (`memory-sync` runs) are skipped, and the top two notes are pasted in as excerpts with a one-line `Memory:` notice for the person. Questions about recent work ("what did we work on lately?") skip the keyword search and list the newest sessions and projects across the whole vault by date.
- **Prompt search ignore list (optional)**: words the prompt search should never use as keywords, in `~/.config/obmem/query-ignore.txt` (or the path in `OBMEM_QUERY_IGNORE_FILE`). One entry per line, `#` for comments. A capitalised entry such as `Rose` is treated as a name and skipped only when written capitalised, so "rose gold" still counts; a lowercase entry such as `standup` is always skipped; `re:<regex>` removes matching text first. Handy for names of people or agents you mention often, which otherwise crowd out the topic. No file means no extra words.
- **Capture ignore list (optional)**: files whose edits alone should not produce an automatic run note, in `~/.config/obmem/capture-ignore.txt` (or the path in `OBMEM_CAPTURE_IGNORE_FILE`). One glob per line, `#` for comments, `~` expanded, `*` also matches `/`. A turn is skipped only when every file it edited is listed; one unlisted edit and the turn is logged as usual. Meant for files that are already their own record, such as a running notebook.

## 4) First-time setup

```bash
obmem set-vault --vault-path "/absolute/path/to/your/obsidian/vault"
obmem init-project --project "My Project" --with-stub
```

## Update / Uninstall

```bash
pipx upgrade obsidian-cli-memory-bank   # or: pipx install --force git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
pipx uninstall obsidian-cli-memory-bank
```

If you copied the hook scripts (rather than symlinking them), copy all six again after updating: they share `obsidian_hook_common.py`, so mixing old and new copies breaks them. Symlinked hooks update with the repository. See `CHANGELOG.md` for what changed.

To remove hooks, delete the hook scripts and remove the corresponding entries from `settings.json`.
