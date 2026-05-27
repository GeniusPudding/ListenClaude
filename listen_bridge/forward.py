"""Forward a hook payload to a remote Listen-Claude server.

Used by the hook entry scripts when LISTEN_CLAUDE_URL is set in the
environment. The typical deployment is: SSH from a Mac/Windows
workstation into a Linux dev box with `ssh -R 7878:localhost:7878
remote`, install Listen-Claude on the workstation and run its server,
then on the remote set `LISTEN_CLAUDE_URL=http://127.0.0.1:7878` in
.env. The remote's hook subprocesses POST the original Claude Code
payload back through the SSH tunnel; the workstation's server
synthesises + plays locally so the audio comes out of the user's
actual speakers."""

import os
import sys
import time
import urllib.error
import urllib.request

from . import config


_TIMEOUT = float(os.getenv("LISTEN_CLAUDE_FORWARD_TIMEOUT", "5"))


def _log(msg: str) -> None:
    try:
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def is_configured() -> bool:
    """True when this machine is acting as the "remote producer" — i.e.
    LISTEN_CLAUDE_URL points at a server somewhere else (typically the
    user's workstation, reachable via an SSH reverse tunnel)."""
    return bool(config.LISTEN_CLAUDE_URL)


def _enrich_for_remote(raw_body: bytes, event: str) -> bytes:
    """Bake any local-filesystem-dependent context into the payload
    here, on the remote side, before it travels over the wire.

    The only such field today is `transcript_path` on the Stop event —
    Claude Code writes the conversation transcript to a JSONL file
    under the *remote* HOME, but the receiving workstation can't read
    that path. So we resolve the last assistant message here and pin
    it onto the payload as `_listen_claude_text`; the workstation
    consumes the pre-resolved text directly (see
    transcript.extract_last_assistant)."""
    if event != "Stop":
        return raw_body
    try:
        import json as _json
        payload = _json.loads(raw_body.decode("utf-8", errors="replace") or "{}")
    except Exception:
        return raw_body

    from . import transcript
    text = transcript.extract_last_assistant(payload)
    if not text:
        return raw_body
    payload["_listen_claude_text"] = text
    try:
        return _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except Exception:
        return raw_body


def forward(raw_body: bytes, event: str) -> bool:
    """POST the raw hook payload to the configured server. Returns True
    on success (HTTP 2xx); False on any error — caller falls back to
    running locally if forwarding fails."""
    if not config.LISTEN_CLAUDE_URL:
        return False

    url = config.LISTEN_CLAUDE_URL.rstrip("/") + "/hook"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Hook-Event": event,
    }
    if config.LISTEN_CLAUDE_TOKEN:
        headers["Authorization"] = f"Bearer {config.LISTEN_CLAUDE_TOKEN}"

    req = urllib.request.Request(url, data=raw_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                _log(f"forward {event} → HTTP {resp.status}")
            return ok
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        _log(f"forward {event} failed: {e}")
        return False


def forward_or_local(event: str, local_handler) -> int:
    """One-shot helper for hook entry scripts.

    Reads raw stdin once, tries to forward it to the server if a URL is
    configured, and otherwise hands the decoded payload to
    `local_handler(payload)`. Centralises the byte-handling so each
    entry script stays a 5-line file."""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return 0

    if is_configured():
        enriched = _enrich_for_remote(raw, event)
        if forward(enriched, event):
            return 0
        _log(f"forward fell back to local for {event}")

    if not raw:
        return 0
    import json
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"), strict=False)
    except Exception as e:
        _log(f"local {event}: failed to parse stdin: {e}")
        return 0
    return local_handler(payload)
