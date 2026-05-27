"""Per-session state: the rolling one-line "what this window is doing"
title that the Notification hook reads back to disambiguate windows.

One file per Claude Code session_id, with the most recent user prompt
(truncated + cleaned) as the title. Multiple windows on the same
project keep distinct titles, so notifications can announce
「在做 修 noise issue 的視窗,需要你確認」 — uniquely identifying which
window is asking, even with the same project directory."""

import json
import os
import re
import time

from . import config


_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")


def _safe_id(session_id: str) -> str:
    return _SAFE_RE.sub("_", session_id or "_")[:80]


def _path_for(session_id: str) -> str:
    return os.path.join(config.SESSION_STATE_DIR, _safe_id(session_id) + ".json")


def write(session_id: str, *, summary: str = "", project: str = "") -> None:
    """Persist the current activity summary for this session.

    Best-effort: any I/O error is swallowed because losing a session
    title is harmless (notification just falls back to project name)."""
    if not session_id:
        return
    try:
        os.makedirs(config.SESSION_STATE_DIR, exist_ok=True)
        with open(_path_for(session_id), "w", encoding="utf-8") as f:
            json.dump(
                {"summary": summary, "project": project, "ts": time.time()},
                f, ensure_ascii=False,
            )
    except OSError:
        pass


def read(session_id: str) -> dict | None:
    """Return {summary, project, ts} for this session, or None if no
    record exists / file is unreadable."""
    if not session_id:
        return None
    try:
        with open(_path_for(session_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


_CLEAN_PREFIX_RE = re.compile(r"^[#>\-*\s]+")


def summarize_prompt(prompt: str, max_chars: int) -> str:
    """Distill the user's free-form prompt into one short headline used
    as the session title. Takes the first non-empty line, strips
    markdown / code-fence noise, and truncates."""
    if not prompt:
        return ""
    for raw_line in prompt.splitlines():
        line = _CLEAN_PREFIX_RE.sub("", raw_line).strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        return line[:max_chars]
    return ""
