# Install (Fast)

This page is optimized for copy-paste installs.

## 1) Install the CLI

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git
```

If your shell says `obmem` is not found, restart terminal once.

## 2) Verify

```bash
obmem --help
obmem doctor
```

## 3) First-time setup

```bash
obmem set-vault --vault-path "/absolute/path/to/your/obsidian/vault"
obmem init-project --project "My Project" --with-stub
```

## 4) Daily usage

```bash
obmem record-run \
  --project "My Project" \
  --title "What I worked on" \
  --prompt "Short prompt/context" \
  --summary "What changed" \
  --actions "Concrete actions taken" \
  --tags "daily,log"
```

---

## Update / Uninstall

```bash
pipx upgrade obsidian-cli-memory-bank
pipx uninstall obsidian-cli-memory-bank
```

---

## Optional: Hook Integrations

Hooks are optional. Core CLI usage works everywhere without hooks.

### Claude Code

Use the adapter as your hook command (payload comes from stdin):

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/claude_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill
```

### Cursor Webhooks

```bash
python3 /absolute/path/to/obsidian-cli-memory-bank-skill/scripts/cursor_notify_hook.py \
  --skill-repo /absolute/path/to/obsidian-cli-memory-bank-skill
```

Security hardening for Cursor webhook deploys:

```bash
export CURSOR_WEBHOOK_SECRET="your-shared-secret"
# pass signature in CURSOR_WEBHOOK_SIGNATURE or payload.signature
```

### Codex (optional helper installer)

```bash
cd /absolute/path/to/obsidian-cli-memory-bank-skill
chmod +x scripts/install_codex_notify_hook.sh scripts/codex_notify_hook.py
./scripts/install_codex_notify_hook.sh
```

---

## X Post Snippet

```text
New open-source CLI: Obsidian Memory Bank 🧠

Install:
brew install pipx
pipx ensurepath
pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git

Use:
obmem set-vault --vault-path "/path/to/vault"
obmem init-project --project "My Project" --with-stub
obmem record-run --project "My Project" --title "Daily" --prompt "..." --summary "..." --actions "..."
```
