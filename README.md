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

Claude Code hook/event payload formats can vary by environment. Use this adapter as the stable bridge:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/claude_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill \
  '{"type":"turn-complete","workspace":"/path/to/project","messages":[{"role":"user","content":"..."}],"assistant":"..."}'
```

Recommended setup:
- Configure your Claude Code post-turn hook to call `scripts/claude_notify_hook.py`.
- Pass the full event JSON string as the final positional argument.

## Cursor Integration

For Cursor, wire a post-response event to call:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/cursor_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill \
  '<cursor-event-json>'
```

The adapter accepts common Cursor-like keys such as `workspace`, `messages`/`conversation`, and `assistant_message`/`response`.

## Antigravity Integration

For Antigravity environments, wire post-turn notifications to:

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/antigravity_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill \
  '<antigravity-event-json>'
```

The adapter supports nested payloads under `data`, `event`, or `payload` and resolves common message/summary fields.

## Hook Behavior

All notify adapters share the same behavior:
- resolve workspace vault mapping
- create a `record-run` note automatically
- stay non-blocking (never fail your agent turn)
- print visible status messages like `[obsidian-memory-hook-*] running ...` and `[... ] logged run note ...`

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
