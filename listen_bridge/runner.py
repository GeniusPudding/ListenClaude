"""Entry point invoked by Claude Code's Stop hook.

Architecture: producer + cooperative worker.

Each hook invocation:
  1. Resolves the spoken text (summarize / LLM rewrite happens here so
     multiple windows summarize in parallel).
  2. Drops a JSON file into QUEUE_DIR — filename is the wall-clock
     timestamp so lexicographic sort = FIFO.
  3. Tries to atomically claim the worker lock.
     - Claimed: become the worker, drain QUEUE_DIR in order, speak each
       item, delete each file. After the queue stays empty for
       WORKER_GRACE_SEC, release the lock and exit.
     - Already taken: spin until either our file is processed by the
       current worker, or the lock goes stale and we can take over.

Result: no message is ever silently dropped due to concurrent windows.
Every Stop hook either gets spoken by someone, or is currently in the
queue waiting its turn.
"""

import json
import os
import os.path
import sys
import threading
import time
import uuid

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


def _ensure_queue_dir() -> None:
    try:
        os.makedirs(config.QUEUE_DIR, exist_ok=True)
    except OSError as e:
        _log(f"failed to create queue dir {config.QUEUE_DIR}: {e}")


def _enqueue(spoken: str, project: str) -> str:
    """Write a request file to the queue and return its absolute path.

    Uses an atomic write-then-rename so the worker never observes a
    half-written JSON file (Windows + POSIX both honor os.replace).
    """
    _ensure_queue_dir()
    # ns timestamp gives chronological order; pid + uuid break ties so
    # two simultaneous windows never collide on the same filename.
    name = f"{time.time_ns():020d}_{os.getpid()}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(config.QUEUE_DIR, name)
    tmp = path + ".tmp"
    payload = {"spoken": spoken, "project": project, "ts": time.time()}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def _list_queue() -> list[str]:
    """Return queued filenames sorted lexicographically (= chronologically)."""
    try:
        names = [n for n in os.listdir(config.QUEUE_DIR) if n.endswith(".json")]
    except FileNotFoundError:
        return []
    except OSError:
        return []
    names.sort()
    return names


def _read_item(path: str) -> tuple[str | None, float]:
    """Return (spoken_text, enqueue_ts). spoken_text is None on read failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log(f"failed to read queue item {path}: {e}")
        return None, 0.0
    return data.get("spoken"), float(data.get("ts") or 0.0)


def _try_claim_lock() -> bool:
    """Atomically claim the worker lock. Returns True on success."""
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


def _release_lock() -> None:
    try:
        os.unlink(config.LOCK_PATH)
    except OSError:
        pass


def _clear_stale_lock() -> None:
    """Remove the lock file if its mtime hasn't been refreshed recently —
    the worker that owned it must have died without releasing."""
    try:
        if time.time() - os.path.getmtime(config.LOCK_PATH) >= config.LOCK_STALE_SEC:
            try:
                os.unlink(config.LOCK_PATH)
            except OSError:
                pass
    except OSError:
        pass


def _run_worker() -> None:
    """Drain the queue, speaking each item in chronological order.

    Caller must hold the worker lock. Heartbeats lock mtime every few
    seconds so other processes don't consider it stale during long
    playback. Exits after the queue has stayed empty for
    WORKER_GRACE_SEC, which avoids a thundering-handoff race during
    bursty arrivals.
    """
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
        idle_since: float | None = None
        while True:
            if not config.is_enabled():
                # User toggled TTS off mid-playback. Stop draining; leftover
                # items will either be cleaned up by their producers (which
                # also notice the toggle) or aged out by QUEUE_MAX_AGE_SEC.
                return

            files = _list_queue()
            if files:
                idle_since = None
                name = files[0]
                path = os.path.join(config.QUEUE_DIR, name)
                spoken, ts = _read_item(path)
                # Delete first so a TTS crash doesn't cause re-speaking
                # via stale-lock recovery.
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if not spoken:
                    continue
                if ts and time.time() - ts > config.QUEUE_MAX_AGE_SEC:
                    _log(f"drop stale queue item (age {time.time() - ts:.0f}s): {spoken[:40]}")
                    continue
                _log(f"speak ({config.TTS_ENGINE} / {config.TTS_VOICE or 'default'}): {spoken[:80]}")
                try:
                    tts.speak(spoken)
                except Exception as e:
                    _log(f"tts.speak failed: {e}")
                continue

            # Queue is empty — start (or continue) the grace timer.
            now = time.time()
            if idle_since is None:
                idle_since = now
            elif now - idle_since >= config.WORKER_GRACE_SEC:
                return
            time.sleep(0.2)
    finally:
        stop_beat.set()
        beat.join(timeout=1.0)


def _drain_until_done(qfile: str) -> None:
    """Either become the worker and drain the queue, or spin until our
    own item has been picked up by whoever already holds the lock."""
    while True:
        if not config.is_enabled():
            try:
                os.unlink(qfile)
            except OSError:
                pass
            return

        if _try_claim_lock():
            try:
                _run_worker()
            finally:
                _release_lock()
            return

        if not os.path.exists(qfile):
            return

        _clear_stale_lock()
        time.sleep(0.3)


def _format_announcement(announced: str, body: str) -> str:
    """Apply ANNOUNCE_FORMAT to a {project, text} pair with a defensive
    fallback for malformed templates."""
    try:
        return config.ANNOUNCE_FORMAT.format(project=announced, text=body)
    except (KeyError, IndexError, ValueError):
        return f"{announced}: {body}"


def _safe_state_filename(name: str) -> str:
    """Sanitize a project name for use as a flat filename in the notify
    state dir. Keeps alphanumerics (incl. CJK), replaces everything else
    with '_'. Capped at 120 chars so Windows path limits stay safe."""
    out = "".join(ch if ch.isalnum() else "_" for ch in name)
    return (out or "_")[:120]


def _notify_recently_spoke(project: str) -> bool:
    """True iff we already spoke a notification for this project within
    the last NOTIFY_DEDUPE_SEC seconds."""
    if not project or config.NOTIFY_DEDUPE_SEC <= 0:
        return False
    path = os.path.join(config.NOTIFY_STATE_DIR, _safe_state_filename(project))
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    return age < config.NOTIFY_DEDUPE_SEC


def _notify_mark_spoke(project: str) -> None:
    try:
        os.makedirs(config.NOTIFY_STATE_DIR, exist_ok=True)
        path = os.path.join(
            config.NOTIFY_STATE_DIR, _safe_state_filename(project or "_")
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
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

    # Resolve the spoken text in the producer so multiple windows summarize
    # in parallel; the worker just plays audio sequentially. Project name
    # passes through PROJECT_ALIASES (a user-maintained JSON) so cloned
    # voices that only speak the trained language can still pronounce
    # which window is talking.
    project = _project_name(payload) if config.ANNOUNCE_PROJECT else ""
    spoken = summarize.prepare_text(text, config.TTS_MODE, config.TTS_MAX_CHARS)
    if project:
        spoken = _format_announcement(config.project_alias(project), spoken)

    qfile = _enqueue(spoken, project)
    _log(f"enqueued {os.path.basename(qfile)}: {spoken[:60]}")
    _drain_until_done(qfile)
    return 0


def notification_main() -> int:
    """Entry point for Claude Code's Notification hook.

    Speaks a short prompt — by default 「視窗 <project>:需要確認」— when
    Claude Code asks the user a Yes/No permission question. Reuses the
    same FIFO queue as the Stop hook so messages from multiple windows
    still play in order without overlap.

    Filters by NOTIFY_KEYWORDS so idle / non-permission notifications
    don't pester the user, and dedupes within NOTIFY_DEDUPE_SEC per
    project so rapidly-repeated prompts only speak once.
    """
    if not config.is_enabled():
        return 0

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw, strict=False)
    except Exception as e:
        _log(f"notify: failed to parse hook stdin: {e}")
        return 0

    message = str(payload.get("message") or "")
    low = message.lower()
    if config.NOTIFY_KEYWORDS and not any(k in low for k in config.NOTIFY_KEYWORDS):
        _log(f"notify skip (no keyword): {message[:60]}")
        return 0

    project = _project_name(payload) if config.ANNOUNCE_PROJECT else ""
    if _notify_recently_spoke(project):
        _log(f"notify dedupe ({project}): {message[:60]}")
        return 0

    body = config.NOTIFY_BODY
    if project:
        spoken = _format_announcement(config.project_alias(project), body)
    else:
        spoken = body

    _notify_mark_spoke(project)
    qfile = _enqueue(spoken, project)
    _log(f"notify enqueued {os.path.basename(qfile)}: {spoken[:60]}")
    _drain_until_done(qfile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
