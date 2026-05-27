"""UserPromptSubmit hook entry.

Each time the user sends a prompt to a Claude Code session, this
captures the first non-empty line as that session's "current activity"
title. The Notification hook reads it back so spoken Yes/No prompts
can identify which window is asking based on what it's doing
(「在做 修 noise issue 的視窗」), not just the project directory name —
critical when the same project has multiple windows open."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge import config, llm, session
from listen_bridge.runner import _project_name


def main() -> int:
    # Skip the inner `claude -p` summarisation calls — they fire a
    # UserPromptSubmit hook for the rewrite-wrapper prompt, which would
    # otherwise pollute the user's actual session title with our own
    # internal instructions.
    if llm.is_inner_summarization_call():
        return 0

    # Read raw bytes and force UTF-8 decoding. Python on Windows defaults
    # sys.stdin to the legacy ANSI codepage (cp950 in zh-TW), which
    # mangles Chinese characters in the user's prompt into surrogate
    # pairs and breaks json.loads / later file writes.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except Exception:
        return 0
    try:
        payload = json.loads(raw, strict=False)
    except Exception:
        return 0

    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return 0

    prompt = str(payload.get("prompt") or "")
    summary = session.summarize_prompt(prompt, config.SESSION_SUMMARY_MAX_CHARS)
    project = _project_name(payload)

    session.write(session_id, summary=summary, project=project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
