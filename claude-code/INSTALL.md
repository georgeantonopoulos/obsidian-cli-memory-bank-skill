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
- **Stop** (post-stop): Logs a run note with the prompt (read from the transcript), the final reply, and the files changed. By default only turns that edited files are logged; set `OBMEM_STOP_LOG=all` to log every turn or `OBMEM_STOP_LOG=off` to disable.
- **PreCompact** (pre-compaction): Saves the recent prompts to Obsidian before context compression. Prevents knowledge loss when conversations hit context limits.
- **PostToolUse** (post-write/edit): Mirrors Claude Code auto-memory writes (`~/.claude/projects/*/memory/*.md`) to the vault.

All hooks silently no-op when no vault is mapped for the current workspace.

- **Project identity**: hooks use the directory Claude was launched in (`CLAUDE_PROJECT_DIR`, else the git root), so `cd`-ing into a subfolder does not file notes under another project.
- **Secrets**: API keys, bearer tokens, `KEY=value` secrets and long opaque tokens are redacted before any search query, Jev request, or run note.
- **Opt out**: `OBMEM_HOOKS=off` disables all hooks; an empty `.obmem-off` file in a project root disables them for that project.
- **Prompt search**: skips short acknowledgements, ranks proper nouns and `identifiers` ahead of filler words, and prefers distilled notes over `Compactions/`, `Archive/` and `Runs/`. With the Jev ranker enabled it passes the redacted prompt as `--intent` and keeps Jev's order; if no note clears the Jev relevance threshold (`OBMEM_JEV_MIN`, default 0.30) the hook prints nothing.

## 4) First-time setup

```bash
obmem set-vault --vault-path "/absolute/path/to/your/obsidian/vault"
obmem init-project --project "My Project" --with-stub
```

## Update / Uninstall

```bash
pipx upgrade obsidian-cli-memory-bank
pipx uninstall obsidian-cli-memory-bank
```

To remove hooks, delete the hook scripts and remove the corresponding entries from `settings.json`.
