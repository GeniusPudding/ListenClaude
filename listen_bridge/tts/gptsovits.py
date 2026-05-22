"""GPT-SoVITS engine — local GPU TTS with fine-tuned voice cloning.

Architecture mirrors fish.py but talks to GPT-SoVITS's `api_v2.py`
server (POST /tts), which loads fine-tuned GPT + SoVITS checkpoints
plus a per-request reference audio for zero-shot voice conditioning.

The server runs in its own Python 3.10/3.12 venv (.venv-gptsovits/) so
its torch / lightning / fastapi stack is fully isolated from
Listen-Claude's main venv.

Every prerequisite failure (no CUDA, server not running, missing
checkpoints, HTTP error) falls back to TTS_FALLBACK_ENGINE so the user
always hears something.
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

from .. import config


# ---------------------------------------------------------------------------
# Logging — same format / file as fish.py / runner.py

def _log(msg: str) -> None:
    try:
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] gptsovits: {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Preconditions

def _check_cuda() -> tuple[bool, str]:
    """The api_v2 server runs in its own venv with its own torch; the
    main listen_bridge venv may not even have torch. Detection here is
    advisory: if nvidia-smi shows a GPU, assume server can use it.
    Server start itself will fail if anything is wrong."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True, r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, "nvidia-smi not found or no GPU"


def _check_models() -> tuple[bool, str]:
    """Verify the trained GPT + SoVITS .pth/.ckpt files exist."""
    for label, path in (
        ("GPT ckpt",    config.GPTSOVITS_GPT_WEIGHTS),
        ("SoVITS pth",  config.GPTSOVITS_SOVITS_WEIGHTS),
    ):
        if not os.path.isfile(path):
            return False, f"missing {label} at {path}"
    return True, "models ok"


# ---------------------------------------------------------------------------
# Fallback dispatch — never recurses back into gptsovits

_FALLBACK_ALLOWED = {"edge", "system", "piper", "elevenlabs", "fish"}


def _fallback(text: str, reason: str = "") -> None:
    if reason:
        _log(f"fallback ({config.TTS_FALLBACK_ENGINE}): {reason}")
    fb = config.TTS_FALLBACK_ENGINE
    if fb == "gptsovits" or fb not in _FALLBACK_ALLOWED:
        fb = "edge"
    if fb == "edge":
        from . import edge; edge.speak(text)
    elif fb == "fish":
        from . import fish; fish.speak(text)
    elif fb == "piper":
        from . import piper; piper.speak(text)
    elif fb == "elevenlabs":
        from . import elevenlabs; elevenlabs.speak(text)
    else:
        from . import system; system.speak(text)


# ---------------------------------------------------------------------------
# Server lifecycle.

def _server_url(path: str = "") -> str:
    return f"http://{config.GPTSOVITS_HOST}:{config.GPTSOVITS_PORT}{path}"


def _is_port_open(timeout: float = 0.3) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((config.GPTSOVITS_HOST, config.GPTSOVITS_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _server_alive(timeout: float = 1.0) -> bool:
    """Port-open is enough — same approach as fish.py's
    cascade-proof health check."""
    return _is_port_open(timeout=0.5)


def _build_server_cmd() -> list[str]:
    """Compose the command to spawn the GPT-SoVITS api_v2 server.

    api_v2.py reads a tts_infer.yaml. We point at our custom config
    file written next to the trained weights, which has paths to the
    fine-tuned GPT + SoVITS plus the shared BERT / HuBERT.
    """
    if config.GPTSOVITS_SERVER_CMD:
        return shlex.split(config.GPTSOVITS_SERVER_CMD, posix=not config.IS_WIN)

    return [
        config.GPTSOVITS_PYTHON,
        config.GPTSOVITS_API_SCRIPT,
        "-a", config.GPTSOVITS_HOST,
        "-p", str(config.GPTSOVITS_PORT),
        "-c", config.GPTSOVITS_TTS_INFER_YAML,
    ]


def _try_start_server() -> bool:
    """Spawn the api_v2 server as a detached background process and
    wait for it to bind the port. Cascade guard: if the port is already
    bound, trust the existing listener and skip the spawn."""
    if _is_port_open(timeout=0.3):
        _log("port already bound — trusting existing server")
        return True

    cmd = _build_server_cmd()
    _log(f"starting server: {' '.join(cmd)}")

    log_path = os.path.join(tempfile.gettempdir(), "listen-claude-gptsovits-server.log")
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
    except OSError as e:
        _log(f"could not open server log file: {e}")
        return False

    # Detached so the server outlives the Stop-hook Python process.
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        # Add GPT_SoVITS/ + repo root to PYTHONPATH for bare-package imports
        "PYTHONPATH": (
            os.path.join(config.GPTSOVITS_SOURCE_DIR, "GPT_SoVITS")
            + os.pathsep + config.GPTSOVITS_SOURCE_DIR
            + os.pathsep + os.environ.get("PYTHONPATH", "")
        ).rstrip(os.pathsep),
        # Intel Fortran handler can crash detached children on Windows.
        "FOR_DISABLE_CONSOLE_CTRL_HANDLER": "1",
        "KMP_HANDLE_SIGNALS": "0",
    }
    kwargs: dict = {
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "env": env,
        "cwd": config.GPTSOVITS_SOURCE_DIR,
    }
    if config.IS_WIN:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
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

    deadline = time.time() + config.GPTSOVITS_STARTUP_TIMEOUT_SEC
    while time.time() < deadline:
        if _server_alive(timeout=1.0):
            _log("server is up")
            return True
        time.sleep(0.5)

    _log(f"server didn't come up within {config.GPTSOVITS_STARTUP_TIMEOUT_SEC}s "
         f"— see {log_path} for stderr")
    return False


# ---------------------------------------------------------------------------
# Synthesis request.

def _request_synthesis(text: str) -> bytes | None:
    """POST text to api_v2's /tts endpoint and return WAV bytes.

    The endpoint expects: text, text_lang, ref_audio_path, prompt_text,
    prompt_lang, and a bunch of sampling params. We pull the reference
    audio + transcript from the same voice profile dir as fish.py uses,
    so a single voices/<name>/ folder works with either engine.
    """
    ref_path = config.GPTSOVITS_REFERENCE_VOICE
    ref_text = config.GPTSOVITS_REFERENCE_TEXT

    # Fall back to FISH_VOICE_DIR's first reference if no dedicated ref
    # was set — keeps single-voice setups DRY.
    if (not ref_path or not os.path.isfile(ref_path)) and config.FISH_VOICE_DIR:
        candidate_wav = os.path.join(config.FISH_VOICE_DIR, "reference.wav")
        candidate_txt = os.path.join(config.FISH_VOICE_DIR, "reference.txt")
        if os.path.isfile(candidate_wav):
            ref_path = candidate_wav
            if not ref_text and os.path.isfile(candidate_txt):
                try:
                    with open(candidate_txt, encoding="utf-8") as f:
                        ref_text = f.read().strip()
                except OSError:
                    pass

    if not ref_path:
        _log("no reference voice configured (set GPTSOVITS_REFERENCE_VOICE)")
        return None

    # api_v2 reads the reference path relative to its own cwd (the
    # GPT-SoVITS source dir), not ours — so it would resolve
    # "voices/ig-demo/reference-c.wav" against ~/.cache/gpt-sovits-source/
    # and return "not exists". Always send an absolute path.
    ref_path = os.path.abspath(ref_path)
    if not os.path.isfile(ref_path):
        _log(f"reference voice file not found: {ref_path}")
        return None

    # All sampling / speed knobs are env-driven via config so they can
    # be tuned per-voice without code edits.
    body = {
        "text": text,
        "text_lang": config.GPTSOVITS_TEXT_LANG,
        "ref_audio_path": ref_path,
        "prompt_text": ref_text or "",
        "prompt_lang": config.GPTSOVITS_PROMPT_LANG,
        "top_k": config.GPTSOVITS_TOP_K,
        "top_p": config.GPTSOVITS_TOP_P,
        "temperature": config.GPTSOVITS_TEMPERATURE,
        "text_split_method": config.GPTSOVITS_TEXT_SPLIT,
        "batch_size": 1,
        "speed_factor": config.GPTSOVITS_SPEED_FACTOR,
        "fragment_interval": config.GPTSOVITS_FRAGMENT_INTERVAL,
        "repetition_penalty": config.GPTSOVITS_REPETITION_PENALTY,
        "media_type": "wav",
        "streaming_mode": False,
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _server_url("/tts"),
        data=data,
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=config.GPTSOVITS_SYNTH_TIMEOUT_SEC) as r:
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
            body_preview = e.read()[:300].decode("utf-8", errors="replace")
        except Exception:
            pass
        _log(f"server HTTP {e.code}: {body_preview}")
        return None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        _log(f"server request failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Playback — same helpers as edge / fish.

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
                subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
                return
            except FileNotFoundError:
                continue


# ---------------------------------------------------------------------------
# Public entry point.

def speak(text: str) -> None:
    """Synthesize via GPT-SoVITS, or fall back if any precondition fails."""
    if not text:
        return

    ok, why = _check_cuda()
    if not ok:
        _fallback(text, reason=f"no CUDA → {why}")
        return

    ok, why = _check_models()
    if not ok:
        _fallback(text, reason=f"no models → {why}")
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
