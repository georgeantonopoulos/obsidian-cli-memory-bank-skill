#!/usr/bin/env python3
"""Cursor webhook adapter for Obsidian memory logging.

Docs reference: https://docs.cursor.com/background-agent/webhooks
Cursor background-agent webhooks include payload fields such as:
- event, status, timestamp, id, source, target, summary
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.hook_common import (
    content_to_text,
    hook_notice,
    log_turn,
    read_json_payload,
    resolve_path,
    truncate,
)


def _load_payload(raw_json: Optional[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = raw_json if raw_json is not None else sys.stdin.read().strip()
    if not raw:
        return None, ""
    return read_json_payload(raw), raw


def _extract_signature(payload: Dict[str, Any]) -> str:
    # Signatures are often passed via HTTP headers in wrapper scripts.
    for env_name in ["CURSOR_WEBHOOK_SIGNATURE", "CURSOR_SIGNATURE"]:
        value = os.environ.get(env_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = payload.get("signature")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _validate_signature(raw_payload: str, payload: Dict[str, Any]) -> bool:
    secret = os.environ.get("CURSOR_WEBHOOK_SECRET", "").strip()
    if not secret:
        # Optional by design for local/dev usage.
        return True

    signature = _extract_signature(payload)
    if not signature:
        hook_notice("obsidian-memory-hook-cursor", "missing webhook signature while CURSOR_WEBHOOK_SECRET is set; skipping")
        return False

    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), raw_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        hook_notice("obsidian-memory-hook-cursor", "webhook signature mismatch; skipping")
        return False
    return True


def _messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ["messages", "chat_messages", "conversation", "transcript"]:
        value = payload.get(key)
        if isinstance(value, list):
            out = [item for item in value if isinstance(item, dict)]
            if out:
                return out
    return []


def _repo_name_from_source(payload: Dict[str, Any]) -> str:
    source = payload.get("source")
    if not isinstance(source, dict):
        return ""
    repo = source.get("repository")
    if not isinstance(repo, str) or not repo.strip():
        return ""
    # e.g., "owner/repo" or URL ending in repo
    repo = repo.strip().rstrip("/")
    if "/" in repo:
        return repo.split("/")[-1] or ""
    return repo


def extract_prompt(payload: Dict[str, Any]) -> str:
    msgs = _messages(payload)
    user_parts: List[str] = []
    for msg in msgs:
        role = str(msg.get("role", msg.get("author", ""))).lower()
        if role in {"user", "human"}:
            user_parts.append(content_to_text(msg.get("content") or msg.get("text")))

    prompt = "\n\n".join([t for t in user_parts if t.strip()])
    if not prompt and isinstance(payload.get("prompt"), str):
        prompt = payload["prompt"]
    if not prompt and isinstance(payload.get("summary"), str):
        # Cursor webhooks commonly provide summary when raw chat transcript is absent.
        prompt = payload["summary"]

    return truncate(prompt or "No user prompt captured.", 3000)


def extract_summary(payload: Dict[str, Any]) -> str:
    for key in ["assistant_message", "last_assistant_message", "response", "output", "summary"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            status = payload.get("status")
            if isinstance(status, str) and status.strip() and key == "summary":
                return truncate(f"{value} (status: {status})", 500)
            return truncate(value, 500)

    msgs = _messages(payload)
    assistant_parts: List[str] = []
    for msg in msgs:
        role = str(msg.get("role", msg.get("author", ""))).lower()
        if role in {"assistant", "ai"}:
            assistant_parts.append(content_to_text(msg.get("content") or msg.get("text")))
    summary = "\n\n".join([t for t in assistant_parts if t.strip()])
    return truncate(summary or "No assistant summary captured.", 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor webhook adapter for Obsidian memory bank")
    parser.add_argument("--skill-repo", required=True, help="Path to obsidian-cli-memory-bank-skill repo")
    parser.add_argument("event_json", nargs="?", help="Optional JSON payload (stdin is the default)")
    args = parser.parse_args()

    payload, raw_payload = _load_payload(args.event_json)
    if payload is None:
        hook_notice("obsidian-memory-hook-cursor", "received empty/invalid JSON payload; skipping")
        return 0
    if not _validate_signature(raw_payload, payload):
        return 0

    event_name = str(payload.get("event") or payload.get("type") or "").strip()
    if not event_name:
        hook_notice("obsidian-memory-hook-cursor", "missing event/type; skipping")
        return 0

    workspace = payload.get("workspace") or payload.get("cwd") or payload.get("project")
    if not workspace:
        workspace = os.environ.get("CURSOR_WORKSPACE") or os.environ.get("CURSOR_PROJECT_DIR")

    workspace_path = resolve_path(workspace)
    skill_repo = Path(args.skill_repo).resolve()

    repo_name = _repo_name_from_source(payload)
    project_name = repo_name or Path(workspace_path).name or "Project"
    turn_id = str(payload.get("id") or payload.get("turnId") or payload.get("turn_id") or "unknown-turn")

    return log_turn(
        prefix="obsidian-memory-hook-cursor",
        skill_repo=skill_repo,
        workspace_path=workspace_path,
        project_name=project_name,
        turn_id=turn_id,
        prompt=extract_prompt(payload),
        summary=extract_summary(payload),
        actions=f"Auto-captured from Cursor webhook event '{event_name}'.",
        tags="cursor,auto-log",
    )


if __name__ == "__main__":
    sys.exit(main())
