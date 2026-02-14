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

2. Set the vault path once for your current workspace:

```bash
python3 scripts/obsidian_memory.py set-vault --vault-path "/absolute/path/to/your/vault"
```

3. Bootstrap a project memory tree:

```bash
python3 scripts/obsidian_memory.py bootstrap --project "My Project"
```

4. Record each meaningful run:

```bash
python3 scripts/obsidian_memory.py record-run \
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
python3 scripts/obsidian_memory.py audit --project "My Project"
```

## Install In Codex

Copy or symlink the skill into your Codex skills directory:

```bash
mkdir -p "$CODEX_HOME/skills"
cp -R ./ "$CODEX_HOME/skills/obsidian-cli-memory-bank"
```

Then trigger it by mentioning `obsidian-cli-memory-bank` in your task.

## Install In Claude / Gemini CLI / Other Agents

Not all agents support the same native "skill" format. Use this universal fallback:

1. Keep this repository on disk.
2. Load `SKILL.md` into your agent's system prompt, workspace instructions, or reusable command profile.
3. Allow the agent to execute `scripts/obsidian_memory.py` commands from this repo.
4. Keep `references/obsidian-cli-patterns.md` available for retrieval patterns.

Suggested agent prompt snippet:

```text
Use the Obsidian CLI Memory Bank workflow from SKILL.md in this repository.
Always resolve or ask for vault path first, persist it, create interlinked notes with wikilinks,
append run logs, and run periodic audit checks (unresolved/orphans/deadends/backlinks).
```

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
python3 -m unittest scripts.tests.test_obsidian_memory -v
```

## License

No explicit license file is included yet. Add one if you plan to distribute broadly.
