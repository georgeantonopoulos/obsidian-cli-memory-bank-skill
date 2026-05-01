# Obsidian CLI Memory Bank

A portable skill that gives AI coding agents persistent, structured memory inside Obsidian. Works across runtimes — Claude Code, Codex, Cursor, Antigravity, or anything that can shell out to a CLI.

Each project gets its own interlinked note graph: a home page, a map of content, a decision log, a run log, and timestamped session notes — all wired together with wikilinks so Obsidian's backlink graph becomes a navigable project history.

## What It Does

- **Vault mapping** — Associates a workspace directory with an Obsidian vault path. Ask once, persist forever.
- **Project scaffolding** — Creates `Project Memory/<project>/` with Home, MOC, Run Log, Decisions, and Open Questions notes, pre-linked to each other.
- **Run logging** — Records each agent session as a structured note: what was asked, what changed, why, and what's still open.
- **Memory compaction** — Distills noisy `Runs/` history into `Current Memory`, topic notes, and archived evidence notes without deleting raw sources.
- **Context retrieval** — Searches the vault before answering so prior decisions and context surface automatically.
- **Graph hygiene** — Audits for unresolved links, orphan notes, dead ends, and backlink coverage.

## Install

```bash
# Install the CLI (isolated via pipx)
brew install pipx && pipx ensurepath
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git

# Verify
obmem doctor
```

**Requirements**: Python 3.10+ and write access to the vault folder. `obmem` uses file-backed vault
operations for create, append, read, search, and audit, so Obsidian desktop does not need to be
running. If `obsidian-cli` is installed, `doctor` reports it as an optional helper, but the memory
bank does not depend on the app IPC bridge.

## Quick Start

```bash
# 1. Map your workspace to a vault
obmem set-vault --vault-path "/path/to/your/obsidian/vault"

# 2. Bootstrap a project
obmem init-project --project "My Project" --with-stub

# 3. Record a session
obmem record-run \
  --project "My Project" \
  --title "Implement queue retry" \
  --summary "Added retry model and queue wiring." \
  --prompt "User asked for per-item retry in export queue." \
  --actions "Updated queue item state, manager logic, and UI actions." \
  --decisions "Retry count defaults to 2 for safety." \
  --tags "queue,retry"

# 4. Search for prior context
obmem search --project "My Project" --query "retry queue"

# 5. Audit graph health
obmem audit --project "My Project"

# 6. Compact noisy run history into useful memory
obmem compact-project --project "My Project"
```

## Runtime Integrations

The skill works anywhere an agent can run shell commands. For runtimes with lifecycle hooks, adapter scripts automate the memory operations at the right moments:

| Lifecycle Point | What Happens | Claude Code | Codex |
|----------------|-------------|-------------|-------|
| Session start | Health-check vault connectivity | `SessionStart` | — |
| Before response | Search vault for relevant context | `UserPromptSubmit` | — |
| After response | Log a structured run note | `Stop` | `agent-turn-complete` |
| Before compaction | Persist transcript before context compression | `PreCompact` | — |
| After memory write | Mirror `MEMORY.md` to vault | `PostToolUse` | — |

### Claude Code

Full integration with 5 lifecycle hooks. See [`claude-code/INSTALL.md`](claude-code/INSTALL.md) for setup.

```bash
# 1. Install CLI (if not done above)
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git

# 2. Install the skill
mkdir -p ~/.claude/skills/obsidian-cli-memory-bank
cp claude-code/SKILL.md ~/.claude/skills/obsidian-cli-memory-bank/SKILL.md

# 3. Install hooks
cp claude-code/hooks/*.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/obsidian_*.py

# 4. Add hook entries to ~/.claude/settings.json (see INSTALL.md for JSON)
```

**Hooks provided:**

| Script | Event | Purpose |
|--------|-------|---------|
| `obsidian_sessionstart_hook.py` | `SessionStart` | Validates vault health once per session |
| `obsidian_preprompt_hook.py` | `UserPromptSubmit` | Searches Obsidian before each response |
| `obsidian_poststop_hook.py` | `Stop` | Logs a run note after each agent stop |
| `obsidian_precompact_hook.py` | `PreCompact` | Saves transcript summary before context compression |
| `obsidian_memory_sync_hook.py` | `PostToolUse` | Mirrors `MEMORY.md` writes to vault |

All hooks silently no-op when no vault is mapped for the current workspace.

### Codex

```bash
# Install the skill
mkdir -p "$CODEX_HOME/skills"
cp -R ./ "$CODEX_HOME/skills/obsidian-cli-memory-bank"

# Install the notify hook (auto-logs each turn)
chmod +x scripts/install_codex_notify_hook.sh scripts/codex_notify_hook.py
./scripts/install_codex_notify_hook.sh
```

The installer is non-destructive — it won't overwrite unmanaged `notify = ...` settings in `~/.codex/config.toml`.

### Cursor

For Cursor background-agent webhooks:

```bash
python3 /path/to/obsidian-cli-memory-bank-skill/scripts/cursor_notify_hook.py \
  --skill-repo /path/to/obsidian-cli-memory-bank-skill
```

Supports webhook fields: `event`, `status`, `id`, `summary`, `source`, `target`, and optional transcript fields (`messages`/`conversation`).

**Optional security hardening:**
- Set `CURSOR_WEBHOOK_SECRET` for HMAC-SHA256 verification
- Pass signature via `CURSOR_WEBHOOK_SIGNATURE` or include `signature` in the payload

If your payload lacks a workspace path, set `CURSOR_WORKSPACE` or `CURSOR_PROJECT_DIR`.

### Antigravity

No stable public hook spec exists for Antigravity yet. Use direct CLI calls:

```bash
obmem record-run --project "Your Project" --title "Task summary" --summary "What changed and why"
```

If your setup emits machine-readable turn events (e.g. via an embedded extension hook flow), the adapter script handles nested payloads:

```bash
python3 /path/to/obsidian-cli-memory-bank-skill/scripts/antigravity_notify_hook.py \
  --skill-repo /path/to/obsidian-cli-memory-bank-skill
```

### Other Runtimes

For any agent that can run shell commands:

1. Load `SKILL.md` into your agent's system prompt or project instructions.
2. Run `obmem` commands before/after tasks.
3. If the runtime exposes lifecycle events, adapt the hook scripts in `claude-code/hooks/` or `scripts/` — the pattern is always: parse the event payload, call `obmem` with the right arguments.

## Repository Structure

```
├── SKILL.md                          # Universal skill instructions (all runtimes)
├── claude-code/
│   ├── SKILL.md                      # Claude Code-native skill (uses obmem CLI)
│   ├── INSTALL.md                    # Claude Code setup guide
│   └── hooks/                        # 5 lifecycle hook scripts
├── scripts/
│   ├── obsidian_memory.py            # Core CLI (also available as obmem via pipx)
│   ├── hook_common.py                # Shared hook runtime helpers
│   ├── codex_notify_hook.py          # Codex adapter
│   ├── claude_notify_hook.py         # Claude Code adapter (package-based alternative)
│   ├── cursor_notify_hook.py         # Cursor webhook adapter
│   ├── antigravity_notify_hook.py    # Antigravity adapter (best-effort)
│   ├── install_codex_notify_hook.sh  # Codex hook installer
│   └── tests/                        # Unit tests for all adapters
├── references/
│   └── obsidian-cli-patterns.md      # Obsidian CLI command reference
└── agents/
    └── openai.yaml                   # UI metadata for compatible systems
```

## CLI Reference

```bash
obmem show-vault                      # Display mapped vault for current workspace
obmem set-vault --vault-path "..."    # Map workspace to vault
obmem doctor                          # Health check (CLI, app, vault, permissions)
obmem bootstrap --project "Name"      # Create project note structure
obmem init-project --project "Name"   # Bootstrap + stub content in one step
obmem record-run --project "Name" ... # Log a session note
obmem compact-project --project "Name" # Distill Runs/ into Current Memory, Topics, and Archive/Runs
obmem compact-project --project "Name" --include-archive # Re-distill archived evidence after improving rules
obmem search --project "Name" -q "x"  # Search vault by keyword
obmem read-note --path "..."          # Read a specific note
obmem audit --project "Name"          # Check graph hygiene
obmem set-audit-frequency --runs N    # Auto-audit every N runs (0 = off)
```

Use `--workspace "/path"` on any command to target a different workspace.

## Persistence

- Vault mappings persist in `state/vault_config.json` (git-ignored).
- Auto-audit triggers every 5 runs by default (configurable via `set-audit-frequency`).
- `compact-project` moves raw source notes from `Runs/` to `Archive/Runs/`, marks them `status: "compacted"`, prunes noisy run links from hub indexes, and writes the active memory surface to `Current Memory.md` plus `Topics/*.md`.
- Search ranks compacted memory and topic notes ahead of raw run logs, so retrieval starts from distilled knowledge and falls back to archived evidence only when needed.
- Hook adapters are additive — the skill works fine without any hooks installed.

## Tests

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

## Security Notes

- The `state/` directory may contain vault paths; it is git-ignored.
- `.env*`, caches, and platform artifacts are git-ignored.
- Review command output before sharing logs publicly.

## Update / Uninstall

```bash
pipx upgrade obsidian-cli-memory-bank
pipx uninstall obsidian-cli-memory-bank
```

## License

No license file included yet. Add one before distributing broadly.
