"""Extract the last assistant message from Claude Code's Stop-hook payload.

Claude Code pipes a JSON object on stdin when the Stop hook fires. The
exact schema varies by version but generally includes a `transcript_path`
pointing to the session's JSONL transcript. We tail it and grab the most
recent assistant message.
"""

import json
import os


def _read_jsonl(path: str):
    """Yield JSON objects from a .jsonl file, newest-friendly."""
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def extract_last_assistant(stop_payload: dict) -> str:
    """Return the text of the most recent assistant message, or "" if none.

    When the payload was forwarded from a remote machine (SSH tunnel
    case), the local transcript file isn't accessible here, so the
    remote pre-resolves the text on its side and stores it under
    `_listen_claude_text`. We honour that field first; only fall back
    to reading transcript_path if the payload is local."""
    pre = stop_payload.get("_listen_claude_text")
    if pre:
        return str(pre).strip()
    transcript_path = stop_payload.get("transcript_path") or ""
    last_text = ""
    for entry in _read_jsonl(transcript_path):
        # Common shapes across Claude Code versions:
        # { "type": "assistant", "message": {"content": [{"type":"text","text":"..."}]}}
        # { "role": "assistant", "content": "..." }
        msg = entry.get("message") or entry
        role = msg.get("role") or entry.get("type") or ""
        if role != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            last_text = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            if parts:
                last_text = "\n".join(parts)
    return last_text.strip()
