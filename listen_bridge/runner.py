"""Entry point invoked by Claude Code's Stop hook.

Usage: stdin receives the hook JSON payload; this module reads it,
extracts the last assistant message, prepares text per TTS_MODE, and
hands it to the configured TTS engine.
"""

import json
import os
import os.path
import sys
import threading
import time

from . import config, summarize, transcript, tts


def _log(msg: str) -> None:
    try:
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _project_name(payload: dict) -> str:
    """Extract a short, human-readable project / window name from the hook
    payload, used as a spoken prefix so the user knows which window is
    talking."""
    cwd = payload.get("cwd") or ""
    if cwd:
        return os.path.basename(cwd.rstrip("/\\")) or cwd
    tp = payload.get("transcript_path") or ""
    if tp:
        # Claude Code stores transcripts under ~/.claude/projects/<sanitized>/.
        # The sanitized name uses '-' instead of '/'; take the last segment.
        parts = tp.replace("\\", "/").split("/")
        for i, p in enumerate(parts):
            if p == "projects" and i + 1 < len(parts):
                sanitized = parts[i + 1]
                return sanitized.split("-")[-1] or sanitized
    return ""


def _try_claim_lock() -> bool:
    """Atomically claim the lock file. Returns True on success."""
    try:
        fd = os.open(config.LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _acquire_lock(max_wait_sec: float = 240.0) -> bool:
    """Wait up to max_wait_sec for the lock. Returns True if we got it.

    While waiting, periodically clears stale locks (older than
    LOCK_STALE_SEC) and bails out early if the user disables TTS via the
    toggle marker.
    """
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        # Clear stale lock (previous instance crashed / killed).
        try:
            if time.time() - os.path.getmtime(config.LOCK_PATH) >= config.LOCK_STALE_SEC:
                try:
                    os.unlink(config.LOCK_PATH)
                except OSError:
                    pass
        except OSError:
            pass

        if _try_claim_lock():
            return True

        if not config.is_enabled():
            return False
        time.sleep(0.3)
    return False


def _release_lock() -> None:
    try:
        os.unlink(config.LOCK_PATH)
    except OSError:
        pass


def main() -> int:
    if not config.is_enabled():
        return 0

    # If we're the `claude -p` subprocess spawned by TTS_MODE=llm, the
    # Stop hook fires again — bail out so we don't recurse forever.
    from . import llm
    if llm.is_inner_summarization_call():
        return 0

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw, strict=False)
    except Exception as e:
        _log(f"failed to parse hook stdin: {e}")
        return 0

    text = transcript.extract_last_assistant(payload)
    if not text:
        _log("no assistant message found")
        return 0

    if len(text.split()) < config.TTS_MIN_WORDS and len(text) < config.TTS_MIN_WORDS * 2:
        _log(f"skip (too short): {text[:40]}")
        return 0

    if not _acquire_lock():
        _log("timed out waiting in TTS queue; dropping")
        return 0

    # Heartbeat: refresh lock mtime every few seconds so concurrent waiters
    # don't consider it stale during long playback. Without this, a TTS
    # session longer than LOCK_STALE_SEC would let the next queued hook
    # barge in and start speaking on top of us.
    stop_beat = threading.Event()

    def _heartbeat() -> None:
        while not stop_beat.wait(5.0):
            try:
                os.utime(config.LOCK_PATH, None)
            except OSError:
                return

    beat = threading.Thread(target=_heartbeat, daemon=True)
    beat.start()

    try:
        spoken = summarize.prepare_text(text, config.TTS_MODE, config.TTS_MAX_CHARS)
        if config.ANNOUNCE_PROJECT:
            project = _project_name(payload)
            if project:
                spoken = f"{project}: {spoken}"
        _log(f"speak ({config.TTS_ENGINE} / {config.TTS_VOICE or 'default'}): {spoken[:80]}")
        tts.speak(spoken)
    finally:
        stop_beat.set()
        beat.join(timeout=1.0)
        _release_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
