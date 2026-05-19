"""fish-speech engine — local GPU TTS with native Chinese/English code-switching.

Architecture
------------
Fish-speech needs ~10 s to load its model into VRAM, which is prohibitive
to pay per Stop hook. Instead we keep a long-lived API-server subprocess
running on FISH_HOST:FISH_PORT (the official `python -m tools.api_server`
from the fish-speech repo) and just POST text to it for each synthesis.

The first speak() call after a cold machine auto-spawns the server and
waits up to FISH_STARTUP_TIMEOUT_SEC for it to come up; subsequent calls
hit a warm server and return in ~1-2 s. The server self-terminates after
FISH_IDLE_TIMEOUT_SEC of inactivity to free VRAM.

Safety net
----------
EVERY failure path falls back to TTS_FALLBACK_ENGINE (default `edge`) so
the user always hears something. The chain is:

    fish.speak()
      └─ no CUDA / FISH_FORCE_CPU off            → _fallback()
      └─ fish-speech / torch not importable      → _fallback()
      └─ checkpoints missing under FISH_MODEL_DIR → _fallback()
      └─ server failed to start / didn't respond → _fallback()
      └─ HTTP request failed / non-2xx           → _fallback()
      └─ empty audio payload                     → _fallback()

This means TTS_ENGINE=fish is safe to ship to a machine without a GPU:
it'll log the reason and just behave like TTS_ENGINE=edge.
"""

import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .. import config


# ---------------------------------------------------------------------------
# Logging helper — same format as the rest of Listen-Claude.

def _log(msg: str) -> None:
    try:
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] fish: {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Precondition checks — each returns (ok: bool, reason: str).

def _check_cuda() -> tuple[bool, str]:
    """Confirm a usable PyTorch + CUDA setup. Skipped when FISH_FORCE_CPU=1."""
    if config.FISH_FORCE_CPU:
        return True, "FISH_FORCE_CPU=1 (running on CPU, slow)"
    try:
        import torch  # noqa: F401  (heavy import; do it lazily)
    except Exception as e:
        return False, f"torch not importable ({e!r})"
    try:
        import torch
        if not torch.cuda.is_available():
            return False, "torch.cuda.is_available() is False"
    except Exception as e:
        return False, f"torch.cuda probe failed ({e!r})"
    return True, "CUDA available"


def _check_model_dir() -> tuple[bool, str]:
    """Confirm the model directory exists and is non-empty."""
    d = config.FISH_MODEL_DIR
    if not os.path.isdir(d):
        return False, f"FISH_MODEL_DIR not found: {d}"
    try:
        if not any(os.scandir(d)):
            return False, f"FISH_MODEL_DIR is empty: {d}"
    except OSError as e:
        return False, f"FISH_MODEL_DIR not readable ({e})"
    return True, d


# ---------------------------------------------------------------------------
# Fallback dispatch — never recurses back into fish.

_FALLBACK_ALLOWED = {"edge", "system", "piper", "elevenlabs"}


def _fallback(text: str, reason: str = "") -> None:
    if reason:
        _log(f"fallback ({config.TTS_FALLBACK_ENGINE}): {reason}")
    fb = config.TTS_FALLBACK_ENGINE
    if fb not in _FALLBACK_ALLOWED:
        # Defensive: user set TTS_FALLBACK_ENGINE=fish (infinite loop) or
        # to something unknown. Use system as the last-resort baseline.
        fb = "system"
    if fb == "edge":
        from . import edge; edge.speak(text)
    elif fb == "piper":
        from . import piper; piper.speak(text)
    elif fb == "elevenlabs":
        from . import elevenlabs; elevenlabs.speak(text)
    else:
        from . import system; system.speak(text)


# ---------------------------------------------------------------------------
# Server lifecycle.

def _server_url(path: str = "") -> str:
    return f"http://{config.FISH_HOST}:{config.FISH_PORT}{path}"


def _is_port_open(timeout: float = 0.3) -> bool:
    """Cheap TCP probe — fish-speech's API server may take a few seconds
    after binding before /docs responds, but the socket is up immediately."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((config.FISH_HOST, config.FISH_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _server_alive(timeout: float = 1.0) -> bool:
    """Full health check: socket open AND /docs (FastAPI default) responds."""
    if not _is_port_open(timeout=0.3):
        return False
    try:
        with urllib.request.urlopen(_server_url("/docs"), timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def _build_server_cmd() -> list[str]:
    """Compose the command to spawn the fish-speech API server.

    Order of preference:
      1. FISH_SERVER_CMD (advanced override — verbatim shlex split)
      2. Default `python -m tools.api_server` invocation with paths
         derived from FISH_MODEL_DIR.
    """
    if config.FISH_SERVER_CMD:
        return shlex.split(config.FISH_SERVER_CMD, posix=not config.IS_WIN)

    # Standard fish-speech 1.5 layout under FISH_MODEL_DIR:
    #   <dir>/                                    ← --llama-checkpoint-path
    #   <dir>/firefly-gan-vq-fsq-8x1024-21hz-generator.pth ← --decoder-checkpoint-path
    decoder_pth = os.path.join(
        config.FISH_MODEL_DIR,
        "firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
    )
    cmd = [
        sys.executable, "-m", "tools.api_server",
        "--listen", f"{config.FISH_HOST}:{config.FISH_PORT}",
        "--llama-checkpoint-path", config.FISH_MODEL_DIR,
        "--decoder-checkpoint-path", decoder_pth,
        "--decoder-config-name", "firefly_gan_vq",
    ]
    if config.FISH_FORCE_CPU:
        cmd += ["--device", "cpu"]
    return cmd


def _try_start_server() -> bool:
    """Spawn the API server as a detached background process and wait
    until /docs responds (or FISH_STARTUP_TIMEOUT_SEC elapses).

    Detached so that when the Stop-hook Python exits, the server keeps
    running for the next hook to reuse.
    """
    cmd = _build_server_cmd()
    _log(f"starting server: {' '.join(cmd)}")

    log_path = os.path.join(tempfile.gettempdir(), "listen-claude-fish-server.log")
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
    except OSError as e:
        _log(f"could not open server log file: {e}")
        return False

    # Detached launch — child must survive parent exit.
    kwargs: dict = {
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "env": {**os.environ, "FISH_IDLE_TIMEOUT_SEC": str(int(config.FISH_IDLE_TIMEOUT_SEC))},
        "cwd": os.path.dirname(config.FISH_MODEL_DIR) or None,
    }
    if config.IS_WIN:
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS — keeps child alive
        # after our Python exits and hides any console window.
        kwargs["creationflags"] = 0x00000200 | 0x00000008
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(cmd, **kwargs)
    except FileNotFoundError as e:
        _log(f"server binary not found: {e}")
        log_fh.close()
        return False
    except OSError as e:
        _log(f"spawn failed: {e}")
        log_fh.close()
        return False

    # Poll for readiness — fish-speech's first import is heavy.
    deadline = time.time() + config.FISH_STARTUP_TIMEOUT_SEC
    while time.time() < deadline:
        if _server_alive(timeout=1.0):
            _log("server is up")
            return True
        time.sleep(0.5)

    _log(f"server didn't come up within {config.FISH_STARTUP_TIMEOUT_SEC}s "
         f"— see {log_path} for stderr")
    return False


# ---------------------------------------------------------------------------
# Synthesis request.

def _request_synthesis(text: str) -> bytes | None:
    """POST text to the server, return WAV bytes on success or None on
    any failure. Includes optional reference audio for zero-shot cloning."""
    body: dict = {
        "text": text,
        # fish-speech v1.5 API accepts these top-level fields:
        "format": "wav",
        "chunk_length": 200,
        "max_new_tokens": 1024,
        "top_p": 0.7,
        "repetition_penalty": 1.2,
        "temperature": 0.7,
    }

    # Zero-shot voice clone: include the reference audio + its transcript.
    ref_voice = config.FISH_REFERENCE_VOICE
    if ref_voice and os.path.isfile(ref_voice):
        try:
            import base64
            with open(ref_voice, "rb") as f:
                ref_b64 = base64.b64encode(f.read()).decode("ascii")
            body["references"] = [{
                "audio": ref_b64,
                "text": config.FISH_REFERENCE_TEXT or "",
            }]
        except OSError as e:
            _log(f"couldn't read reference voice {ref_voice}: {e}")

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _server_url("/v1/tts"),
        data=data,
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=config.FISH_SYNTH_TIMEOUT_SEC) as r:
            if not (200 <= r.status < 300):
                _log(f"server HTTP {r.status}")
                return None
            audio = r.read()
            if not audio:
                _log("server returned empty body")
                return None
            return audio
    except urllib.error.HTTPError as e:
        body_preview = ""
        try:
            body_preview = e.read()[:200].decode("utf-8", errors="replace")
        except Exception:
            pass
        _log(f"server HTTP {e.code}: {body_preview}")
        return None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        _log(f"server request failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Playback — shares the cross-platform helpers used by edge / piper.

def _play_wav(path: str) -> None:
    if config.IS_MAC:
        subprocess.run(["afplay", path], check=False)
    elif config.IS_WIN:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            check=False,
        )
    else:
        for cmd in (["aplay", "-q", path], ["paplay", path]):
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                return
            except FileNotFoundError:
                continue


# ---------------------------------------------------------------------------
# Public entry point.

def speak(text: str) -> None:
    """Synthesize via fish-speech, or fall back if any prerequisite is missing.

    Never raises — the worst case is a logged failure and a fallback voice.
    """
    if not text:
        return

    ok, why = _check_cuda()
    if not ok:
        _fallback(text, reason=f"no CUDA → {why}")
        return

    ok, why = _check_model_dir()
    if not ok:
        _fallback(text, reason=f"no model → {why}")
        return

    if not _server_alive(timeout=1.0):
        if not _try_start_server():
            _fallback(text, reason="server unavailable")
            return

    audio = _request_synthesis(text)
    if not audio:
        _fallback(text, reason="synthesis failed")
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        f.write(audio)
    try:
        _play_wav(wav_path)
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass
