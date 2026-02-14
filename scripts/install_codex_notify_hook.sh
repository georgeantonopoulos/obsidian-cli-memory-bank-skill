#!/usr/bin/env bash
set -euo pipefail

# Install/update Codex notify hook for Obsidian memory bank auto-logging.
#
# This script:
# 1) copies hook script to ~/.codex/hooks/obsidian_memory_notify.py
# 2) writes/updates a managed notify block in ~/.codex/config.toml

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
HOOK_DIR="${CODEX_HOME}/hooks"
HOOK_PATH="${HOOK_DIR}/obsidian_memory_notify.py"
CONFIG_PATH="${CODEX_HOME}/config.toml"

mkdir -p "${HOOK_DIR}"
cp "${SCRIPT_DIR}/codex_notify_hook.py" "${HOOK_PATH}"
chmod +x "${HOOK_PATH}"

touch "${CONFIG_PATH}"

START_MARKER="# >>> obsidian-cli-memory-bank notify hook >>>"
END_MARKER="# <<< obsidian-cli-memory-bank notify hook <<<"
BLOCK="$(cat <<EOF_BLOCK
${START_MARKER}
notify = ["python3", "${HOOK_PATH}", "--skill-repo", "${REPO_ROOT}"]
${END_MARKER}
EOF_BLOCK
)"

if grep -Fq "${START_MARKER}" "${CONFIG_PATH}"; then
  awk -v start="${START_MARKER}" -v end="${END_MARKER}" '
    $0==start {inblock=1; next}
    $0==end {inblock=0; next}
    !inblock {print}
  ' "${CONFIG_PATH}" > "${CONFIG_PATH}.tmp"
  mv "${CONFIG_PATH}.tmp" "${CONFIG_PATH}"
fi

# Remove existing top-level notify assignments to avoid duplicate TOML keys.
PREVIOUS_NOTIFY_LINES="$(grep -E '^[[:space:]]*notify[[:space:]]*=' "${CONFIG_PATH}" || true)"
if [[ -n "${PREVIOUS_NOTIFY_LINES}" ]]; then
  awk '!/^[[:space:]]*notify[[:space:]]*=/' "${CONFIG_PATH}" > "${CONFIG_PATH}.tmp"
  mv "${CONFIG_PATH}.tmp" "${CONFIG_PATH}"
fi

FIRST_TABLE_LINE="$(grep -n '^[[:space:]]*\[' "${CONFIG_PATH}" | head -n 1 | cut -d: -f1 || true)"
TMP_PATH="${CONFIG_PATH}.tmp"
if [[ -n "${FIRST_TABLE_LINE}" && "${FIRST_TABLE_LINE}" -gt 1 ]]; then
  head -n "$((FIRST_TABLE_LINE - 1))" "${CONFIG_PATH}" > "${TMP_PATH}"
else
  : > "${TMP_PATH}"
fi

echo "" >> "${TMP_PATH}"
if [[ -n "${PREVIOUS_NOTIFY_LINES}" ]]; then
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    echo "# previous notify (replaced by installer): ${line}" >> "${TMP_PATH}"
  done <<< "${PREVIOUS_NOTIFY_LINES}"
fi
echo "${BLOCK}" >> "${TMP_PATH}"
echo "" >> "${TMP_PATH}"

if [[ -n "${FIRST_TABLE_LINE}" ]]; then
  tail -n +"${FIRST_TABLE_LINE}" "${CONFIG_PATH}" >> "${TMP_PATH}"
fi
mv "${TMP_PATH}" "${CONFIG_PATH}"

echo "Installed Codex notify hook."
echo "Hook script: ${HOOK_PATH}"
echo "Config file: ${CONFIG_PATH}"
echo ""
echo "Managed block:"
echo "${BLOCK}"
