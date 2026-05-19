"""LLM-backed summarization: call `claude -p` to rewrite Claude's response
as a natural spoken summary (free of markdown, symbols, code, etc.).

Why use the local `claude` CLI instead of the Anthropic SDK directly:

- It picks up the user's existing OAuth / API auth without us needing
  to manage a separate ANTHROPIC_API_KEY env var.
- It uses whatever model the user prefers via --model.
- Failure modes (missing CLI, no auth, timeout) cleanly fall back to
  the regex heuristics in summarize.py.

Recursion guard: the `claude -p` subprocess also triggers our Stop hook
when it finishes its own one-shot turn. We export SENTINEL=1 to its
environment so runner.main() bails out early in the child process,
otherwise summarization would recurse forever.
"""

import os
import shutil
import subprocess

from . import config

SENTINEL = "LISTEN_CLAUDE_SUMMARIZING"

_PROMPT_TEMPLATE = """請把下面這段 Claude 對使用者的回應改寫成適合 TTS 朗讀的口語摘要。

規則:
- 全部用「繁體中文」(Traditional Chinese)輸出,不准用簡體字
- 60 到 120 個字
- 不要念出任何 markdown 符號、code block、URL、表格框、bullet 符號、箭頭、emoji
- 用自然的口語講「做了什麼 / 結論是什麼 / 下一步是什麼」
- 不要加開場白(不要寫「以下是」「Claude 回應」「總結」「摘要」之類的詞)
- 整段只回摘要本體,不要 markdown,不要引號,不要前言

原文:
---
{text}
---"""


def is_inner_summarization_call() -> bool:
    """True when we're the `claude -p` child of another Listen-Claude run."""
    return os.environ.get(SENTINEL) == "1"


def summarize_via_claude(text: str) -> str | None:
    """Ask the local `claude` CLI for a spoken summary.

    Returns the summary string on success, or None on any failure
    (missing CLI, timeout, non-zero exit, empty output) so the caller
    can fall back to a heuristic mode.
    """
    cli = shutil.which("claude")
    if not cli:
        return None

    prompt = _PROMPT_TEMPLATE.format(text=text)
    env = dict(os.environ)
    env[SENTINEL] = "1"
    # Force the child's stdio to UTF-8 on Windows; otherwise Node.js writes
    # the response in the console codepage (cp950 / cp936) and round-trips
    # produce mojibake.
    env["PYTHONIOENCODING"] = "utf-8"

    # Pass the prompt via stdin rather than argv. On Windows, argv goes
    # through the system codepage, which corrupts CJK characters before
    # Claude ever sees them; the model then replies in equally corrupted
    # bytes. `claude -p` reads from stdin when no positional prompt is
    # given, which keeps the payload as clean UTF-8 bytes end-to-end.
    cmd = [cli, "-p"]
    if config.TTS_LLM_MODEL:
        cmd += ["--model", config.TTS_LLM_MODEL]

    try:
        result = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=config.TTS_LLM_TIMEOUT_SEC,
            env=env,
            creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    if not out:
        return None
    return out
