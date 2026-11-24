# Antigravity Integration

Install Obsidian CLI Memory Bank as a native Antigravity plugin bundling both the `obsidian-cli-memory-bank` skill and lifecycle hooks (`SessionStart`, `PreInvocation`, `Stop`).

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

## 2) Install the Antigravity Plugin

Clone the repository (if you have not already) and run the installer:

```bash
git clone https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
cd obsidian-cli-memory-bank-skill
chmod +x antigravity/install.sh antigravity/hooks/run_hook.py
```

### Option A: Global plugin (recommended — symlink for auto-updates)

Makes the skill and hooks available in every Antigravity workspace that has a mapped Obsidian vault (and silently no-ops everywhere else):

```bash
./antigravity/install.sh
```

This symlinks `antigravity/` to `~/.gemini/config/plugins/obsidian-cli-memory-bank`. Future `git pull` updates take effect automatically.

### Option B: Global plugin (self-contained copy)

If you do not want to keep the source checkout around, install a self-contained copy (bundles the shared hook scripts into the plugin's `hooks/` directory):

```bash
./antigravity/install.sh --copy
```

### Option C: Workspace-only plugin (`.agents/plugins/`)

To scope the plugin to a single repository or share it with a team:

```bash
./antigravity/install.sh --workspace /path/to/your/repo --copy
```

### Option D: Manual skill-only install (no hooks)

If you prefer manual `obmem` calls without lifecycle hooks:

```bash
mkdir -p ~/.gemini/config/skills/obsidian-cli-memory-bank/references
cp SKILL.md ~/.gemini/config/skills/obsidian-cli-memory-bank/SKILL.md
cp references/maintenance.md ~/.gemini/config/skills/obsidian-cli-memory-bank/references/maintenance.md
```

## 3) What the hooks do

The plugin's `hooks.json` registers three lifecycle hooks that reuse the same shared hook logic as Claude Code:

| Event | Script | Purpose |
|-------|--------|---------|
| `SessionStart` | `run_hook.py sessionstart` | Validates vault connectivity via `obmem doctor` once per session and injects the recall/capture directive. |
| `PreInvocation` | `run_hook.py preprompt` | Searches Obsidian **once per new user turn** (deduplicated across tool-loop invocations) and injects top note excerpts with a one-line inline `Memory:` notice (`metadata.user_markdown`). Also checks all projects and includes one cross-project note when it outranks the current project. |
| `Stop` | `run_hook.py poststop` | Parses Antigravity's `transcript.jsonl` on normal turn completion (`NO_TOOL_CALL`) and logs a run note for turns that edited files (`write_file`, `edit_file`, `replace_file_content`, `multi_replace_file_content`, `write_to_file`). Skips turns where the agent already ran `obmem record-run`. Always returns `{"decision": "allow"}` so it never blocks stops. |

All hooks silently no-op (`{}` or `{"decision": "allow"}`) when no vault is mapped for the current workspace.

### Configuration & Opt-Out

All shared environment variables and optional config files work identically across Antigravity and Claude Code:

- **Project identity**: Uses the first Antigravity `workspacePaths` entry (resolved to its git root when present), else `cwd`.
- **GUI PATH resilience**: Resolves `obmem` on `PATH`, falling back to `~/.local/bin/obmem`, `/opt/homebrew/bin/obmem`, and `/usr/local/bin/obmem` when a GUI session launches with a minimal `PATH`.
- **Secrets**: API keys, bearer tokens, `KEY=value` secrets, and long opaque tokens are redacted before any search query, Jev request, or run note.
- **Opt out**: Set `OBMEM_HOOKS=off` globally, add an empty `.obmem-off` file to a project root, or toggle the plugin off in Antigravity's Customizations UI.
- **Stop capture mode**: Defaults to `OBMEM_STOP_LOG=edits` (only turns that edited files). Set `OBMEM_STOP_LOG=all` to log every completed turn, or `OBMEM_STOP_LOG=off` to disable auto-capture.
- **Jev relevance threshold**: `OBMEM_JEV_MIN` (default `0.50`) when the optional Jev ranker is enabled.
- **Optional per-user tuning files** (shared across all runtimes):
  - `~/.config/obmem/query-ignore.txt` (`OBMEM_QUERY_IGNORE_FILE`): names, lowercase words, `re:<regex>`, and `skip:<regex>` rules for prompt search.
  - `~/.config/obmem/capture-ignore.txt` (`OBMEM_CAPTURE_IGNORE_FILE`): file globs whose edits alone should not trigger auto-capture.
  - `~/.config/obmem/wrapper-prompts.txt` (`OBMEM_WRAPPER_PROMPTS_FILE`): leading regexes for tool-generated prompts that should be titled from the reply.

## 4) First-time vault setup

```bash
obmem set-vault --vault-path "/absolute/path/to/your/obsidian/vault" --workspace "/path/to/your/workspace"
obmem init-project --project "My Project" --with-stub --workspace "/path/to/your/workspace"
```

## Update / Uninstall

```bash
# Update CLI
pipx upgrade obsidian-cli-memory-bank

# If symlinked: pull the repo
git pull

# If copied: re-run the installer with --copy --force
./antigravity/install.sh --copy --force

# Uninstall the plugin
rm -rf ~/.gemini/config/plugins/obsidian-cli-memory-bank
```
