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
chmod +x ~/.claude/hooks/obsidian_preprompt_hook.py ~/.claude/hooks/obsidian_poststop_hook.py
```

Add hook entries to `~/.claude/settings.json` under the `"hooks"` key:

```json
{
  "hooks": {
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
    ]
  }
}
```

If you already have hooks configured for these events, append the new hook group to the existing array.

### What the hooks do

- **UserPromptSubmit** (pre-prompt): Searches Obsidian for notes relevant to your prompt before Claude answers. Surfaces prior context automatically.
- **Stop** (post-stop): Logs a structured run note to Obsidian after each agent stop. Captures what was asked and what was done.

Both hooks silently no-op when no vault is mapped for the current workspace.

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
