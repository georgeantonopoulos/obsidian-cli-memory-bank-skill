#!/usr/bin/env bash
set -euo pipefail

# Install the Obsidian CLI Memory Bank plugin (skill + lifecycle hooks) into Antigravity.
#
# Usage:
#   ./antigravity/install.sh                      # Symlink globally to ~/.gemini/config/plugins/obsidian-cli-memory-bank
#   ./antigravity/install.sh --copy               # Copy self-contained plugin globally
#   ./antigravity/install.sh --workspace /path    # Symlink into <workspace>/.agents/plugins/obsidian-cli-memory-bank
#   ./antigravity/install.sh --copy --force       # Replace an existing installation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SHARED_HOOKS_DIR="${REPO_ROOT}/claude-code/hooks"

MODE="symlink"
FORCE="false"
TARGET_BASE="${HOME}/.gemini/config/plugins"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy)
      MODE="copy"
      shift
      ;;
    --symlink)
      MODE="symlink"
      shift
      ;;
    --workspace)
      if [[ $# -lt 2 ]]; then
        echo "Error: --workspace requires a directory path" >&2
        exit 1
      fi
      TARGET_BASE="${2%/}/.agents/plugins"
      shift 2
      ;;
    --force)
      FORCE="true"
      shift
      ;;
    -h|--help)
      sed -n '3,10p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

TARGET_DIR="${TARGET_BASE}/obsidian-cli-memory-bank"
mkdir -p "${TARGET_BASE}"

if [[ -e "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
  if [[ "${FORCE}" != "true" ]]; then
    echo "Target already exists: ${TARGET_DIR}" >&2
    echo "Re-run with --force to replace it." >&2
    exit 1
  fi
  rm -rf "${TARGET_DIR}"
fi

if [[ "${MODE}" == "symlink" ]]; then
  ln -s "${SCRIPT_DIR}" "${TARGET_DIR}"
  echo "Symlinked Antigravity plugin: ${TARGET_DIR} -> ${SCRIPT_DIR}"
else
  mkdir -p "${TARGET_DIR}/hooks" "${TARGET_DIR}/skills"
  cp "${SCRIPT_DIR}/plugin.json" "${TARGET_DIR}/plugin.json"
  cp "${SCRIPT_DIR}/hooks.json" "${TARGET_DIR}/hooks.json"
  cp "${SCRIPT_DIR}/INSTALL.md" "${TARGET_DIR}/INSTALL.md"
  cp "${SCRIPT_DIR}/hooks/run_hook.py" "${TARGET_DIR}/hooks/run_hook.py"
  cp -R "${SCRIPT_DIR}/skills/obsidian-cli-memory-bank" "${TARGET_DIR}/skills/obsidian-cli-memory-bank"
  for hook_file in \
    obsidian_hook_common.py \
    obsidian_sessionstart_hook.py \
    obsidian_preprompt_hook.py \
    obsidian_poststop_hook.py
  do
    cp "${SHARED_HOOKS_DIR}/${hook_file}" "${TARGET_DIR}/hooks/${hook_file}"
  done
  chmod +x "${TARGET_DIR}/hooks/"*.py
  echo "Installed self-contained Antigravity plugin: ${TARGET_DIR}"
fi

if ! command -v obmem >/dev/null 2>&1 && [[ ! -x "${HOME}/.local/bin/obmem" ]]; then
  echo "Note: 'obmem' CLI was not found. Install it with:"
  echo "  pipx install git+https://github.com/georgeantonopoulos/obsidian-cli-memory-bank-skill.git"
fi
