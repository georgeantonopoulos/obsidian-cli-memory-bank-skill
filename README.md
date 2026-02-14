# Obsidian CLI Memory Bank Skill

A portable skill/prompt-pack for maintaining a project knowledge base in Obsidian using the Obsidian CLI.

It helps an agent:
- ask for and persist a vault path,
- create structured interlinked notes,
- append run logs and decision trails,
- retrieve context quickly from previous runs,
- audit wikilink graph quality (unresolved links, orphans, deadends, backlinks).

## Repository Contents

- `SKILL.md` - main skill instructions
- `scripts/obsidian_memory.py` - helper CLI for vault mapping + note automation
- `scripts/hook_common.py` - shared helper runtime for notify adapters
- `scripts/codex_notify_hook.py` - Codex notify adapter
- `scripts/claude_notify_hook.py` - Claude Code adapter
- `scripts/cursor_notify_hook.py` - Cursor adapter
- `scripts/antigravity_notify_hook.py` - Antigravity adapter
- `references/obsidian-cli-patterns.md` - Obsidian command patterns
- `agents/openai.yaml` - UI metadata for systems that support it

## Requirements

- Python 3.10+
- Obsidian desktop with Obsidian CLI enabled
- Obsidian CLI available in `PATH` as `obsidian`

## Install In 30 Seconds (Recommended)

Use `pipx` so users get a clean isolated CLI install:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
```

Then use:

```bash
obmem --help
obmem doctor
```

Update later:

```bash
pipx upgrade obsidian-cli-memory-bank
```

Uninstall:

```bash
pipx uninstall obsidian-cli-memory-bank
```

## Quick Start (Universal)

1. Clone this repo:

```bash
git clone https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
cd obsidian-cli-memory-bank-skill
```

Resolve skill path robustly (works even if `CODEX_HOME` is unset):

```bash
if [ -n "${CODEX_HOME:-}" ] && [ -d "$CODEX_HOME/skills/obsidian-cli-memory-bank" ]; then
  SKILL_DIR="$CODEX_HOME/skills/obsidian-cli-memory-bank"
elif [ -d "$HOME/.codex/skills/obsidian-cli-memory-bank" ]; then
  SKILL_DIR="$HOME/.codex/skills/obsidian-cli-memory-bank"
else
  SKILL_DIR="$(pwd)"
fi
```

2. Set the vault path once for your current workspace:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" set-vault --vault-path "/absolute/path/to/your/vault"
```

3. Bootstrap a project memory tree:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" bootstrap --project "My Project"
```

Or do one-step initialization:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" init-project --project "My Project" --with-stub
```

4. Record each meaningful run:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" record-run \
  --project "My Project" \
  --title "Implement queue retry" \
  --prompt "User asked for per-item retry in export queue" \
  --summary "Added retry model and queue wiring" \
  --actions "Updated queue item state, manager logic, and UI actions." \
  --decisions "Retry count defaults to 2 for safety." \
  --questions "Should retries be exponential backoff?" \
  --tags "queue,retry"
```

5. Audit graph hygiene:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" audit --project "My Project"
```

6. Run readiness checks:

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" doctor
```

7. Configure automatic audit cadence (default is every 5 runs):

```bash
python3 "$SKILL_DIR/scripts/obsidian_memory.py" set-audit-frequency --runs 5
```

Set `--runs 0` to disable automatic audits.

## Install In Codex

Copy or symlink the skill into your Codex skills directory:

```bash
mkdir -p "$CODEX_HOME/skills"
cp -R ./ "$CODEX_HOME/skills/obsidian-cli-memory-bank"
```

Then trigger it by mentioning `obsidian-cli-memory-bank` in your task.

### Codex Native Hook (notify)

Codex supports a `notify` command hook that runs when a turn completes (`agent-turn-complete` payload).
This repository includes a ready-to-install hook that auto-logs each Codex turn into the project memory bank.

Install:

```bash
cd /absolute/path/to/obsidian-cli-memory-bank-skill
chmod +x scripts/install_codex_notify_hook.sh scripts/codex_notify_hook.py
./scripts/install_codex_notify_hook.sh
```

Then verify:

```bash
python3 scripts/obsidian_memory.py doctor
```

## Claude Code Integration

Reference docs:
- https://docs.anthropic.com/en/docs/claude-code/hooks

Claude Code hooks send JSON to the hook command via `stdin`.
Use this adapter as the bridge:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/claude_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill
```

Recommended setup:
- Configure your Claude Code post-turn hook to call `scripts/claude_notify_hook.py`.
- Let Claude pipe the native hook payload JSON on stdin.
- The adapter recognizes documented `hook_event_name` values (for example `UserPromptSubmit`, `PostToolUse`, `SessionEnd`).

## Cursor Integration

Reference docs:
- https://docs.cursor.com/background-agent/webhooks

For Cursor background-agent webhooks, pass the webhook payload JSON to:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/cursor_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill
```

The adapter supports documented webhook fields like:
- `event`, `status`, `id`, `summary`, `source`, and `target`
- optional transcript-style fields (`messages`/`conversation`) when available

If your webhook payload does not include a local workspace path, set one via env var:
- `CURSOR_WORKSPACE` or `CURSOR_PROJECT_DIR`

## Antigravity Integration

Current status:
- no stable public hook payload specification was found for Antigravity during implementation
- default recommendation is to use rules/skills + manual `record-run` calls
- this adapter is best-effort and designed for nested payloads seen in local agent tooling

Recommended default in Antigravity:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/obsidian_memory.py record-run \
  --project "Your Project" \
  --title "Task summary" \
  --summary "What changed and why"
```

Only use the adapter below if your setup actually emits machine-readable turn events
(for example when running through an embedded Claude Code extension hook flow):

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/antigravity_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill
```

The adapter supports nested payloads under `data`, `event`, or `payload` and resolves common message/summary fields.

## Hook Behavior

Claude/Cursor adapters share the same behavior:
- resolve workspace vault mapping
- create a `record-run` note automatically
- stay non-blocking (never fail your agent turn)
- print visible status messages like `[obsidian-memory-hook-*] running ...` and `[... ] logged run note ...`

Antigravity adapter behavior:
- same runtime behavior as above when a compatible JSON event is provided
- may no-op in setups that do not expose hook events

## Install In Other Agents (Fallback)

Not all agents expose native hooks. Use this fallback:

1. Keep this repository on disk.
2. Load `SKILL.md` into your agent's system prompt/project instructions.
3. Execute `scripts/obsidian_memory.py` manually before/after major tasks.
4. Use the relevant adapter script if your runtime can emit event JSON.

Suggested prompt snippet:

```text
Use the Obsidian CLI Memory Bank workflow from SKILL.md in this repository.
Always resolve or ask for vault path first, persist it, create interlinked notes with wikilinks,
append run logs, and run periodic audit checks (unresolved/orphans/deadends/backlinks).
```

## Persistence And “Always Use It” Behavior

- Vault mappings persist in `state/vault_config.json`.
- Automatic per-turn behavior depends on your agent runtime exposing hooks/events.
- Adapters in this repo are designed to be resilient to minor payload shape differences.

## Optional: Shell Alias

```bash
alias obmem='python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/obsidian_memory.py'
```

Example:

```bash
obmem show-vault
obmem bootstrap --project "My Project"
```

## Security Notes

- The local `state/` folder can include vault paths; it is git-ignored.
- `.env*`, caches, and platform artifacts are git-ignored.
- Review command output before sharing logs publicly.

## Run Tests

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

## License

No explicit license file is included yet. Add one if you plan to distribute broadly.
