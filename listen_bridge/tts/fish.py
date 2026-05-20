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
    """Health check — port-open is enough to count as alive.

    The fish-speech `kui` ASGI handler is single-threaded for /v1/tts,
    so a server mid-synth can't respond to /docs within our HTTP
    timeout. Treating that as 'dead' caused a fatal cascade: client
    would try to spawn a new server, hit port-collision, fail, and
    fall back to Edge — even though the original server was alive and
    about to return audio.

    A bound TCP listener with no recent close is strong evidence the
    server process is running. Stale TIME_WAIT sockets without an
    owning listener won't pass the SYN check.
    """
    return _is_port_open(timeout=0.5)


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
        "--mode", "tts",
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
    until it responds (or FISH_STARTUP_TIMEOUT_SEC elapses).

    Detached so that when the Stop-hook Python exits, the server keeps
    running for the next hook to reuse.

    Cascade guard: if FISH_PORT is already bound, another process (a
    parallel Stop hook from a sibling window, or a manually-started
    server) is already running or starting one. Trust it and skip the
    spawn — otherwise multiple concurrent spawns race to bind the same
    port, all but one hit WinError 10048, and the survivors eventually
    timeout the caller too.
    """
    if _is_port_open(timeout=0.3):
        _log("port already bound — trusting existing server")
        return True

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
# Text preprocessing — works around fish-speech 1.5 weaknesses on numbers
# and Chinese/English code-switching. These mutate the user-visible spoken
# string, so be conservative.

_DIGITS_ZH = "零一二三四五六七八九"


def _digits_to_chinese(text: str) -> str:
    """Convert Arabic numeric runs to Chinese characters. fish-speech's
    Chinese tokenizer doesn't know how to read `199` or `30` — without
    this it would spell digits letter-by-letter or skip the run. Handles
    up to 5-digit integers (which covers 99% of summary text); longer
    numbers are read digit-by-digit as a fallback."""
    import re

    def _convert_int(n: int) -> str:
        if n == 0:
            return "零"
        if n < 10:
            return _DIGITS_ZH[n]
        if n < 100:
            tens, ones = divmod(n, 10)
            out = ("" if tens == 1 else _DIGITS_ZH[tens]) + "十"
            if ones:
                out += _DIGITS_ZH[ones]
            return out
        if n < 1000:
            hundreds, rem = divmod(n, 100)
            out = _DIGITS_ZH[hundreds] + "百"
            if rem == 0:
                return out
            if rem < 10:
                return out + "零" + _DIGITS_ZH[rem]
            return out + _convert_int(rem)
        if n < 10000:
            thousands, rem = divmod(n, 1000)
            out = _DIGITS_ZH[thousands] + "千"
            if rem == 0:
                return out
            if rem < 100:
                return out + "零" + _convert_int(rem)
            return out + _convert_int(rem)
        if n < 100000:
            wan, rem = divmod(n, 10000)
            out = _DIGITS_ZH[wan] + "萬"
            if rem == 0:
                return out
            if rem < 1000:
                return out + "零" + _convert_int(rem)
            return out + _convert_int(rem)
        # Too large — read digit by digit.
        return "".join(_DIGITS_ZH[int(d)] for d in str(n))

    return re.sub(
        r"\d+",
        lambda m: _convert_int(int(m.group(0))),
        text,
    )


def _space_around_english(text: str) -> str:
    """Insert spaces around runs of ASCII letters so fish-speech treats
    them as discrete English words rather than gluing them onto adjacent
    Chinese characters. `API、commit` → ` API 、 commit `. Idempotent
    over already-spaced text."""
    import re

    # Surround any run of ASCII letters (with optional internal hyphens or
    # dots, e.g. fish-speech, claude.ai) with single spaces.
    out = re.sub(r"([A-Za-z][A-Za-z\-.]*[A-Za-z]|[A-Za-z])", r" \1 ", text)
    # Collapse runs of whitespace.
    return re.sub(r" +", " ", out).strip()


def _preprocess_for_fish(text: str) -> str:
    """Full preprocessor: digit normalization + English word spacing."""
    return _space_around_english(_digits_to_chinese(text))


# ---------------------------------------------------------------------------
# Voice profile loading.

def _load_voice_refs() -> list[dict]:
    """Resolve the list of references to send with each synthesis request.

    Order of preference:
      1. FISH_VOICE_DIR set → load all (ref*.wav, ref*.txt) pairs in the
         directory. If a config.json exists, honor its `references` list
         instead (explicit ordering / partial subset).
      2. FISH_REFERENCE_VOICE + FISH_REFERENCE_TEXT set (legacy) → single
         reference pair.
      3. Neither set → empty list (fish-speech uses its preset voice).

    Returns a list of {"audio": <base64>, "text": <transcript>} dicts
    ready for the /v1/tts request body.
    """
    import base64

    refs: list[tuple[str, str]] = []  # (audio_path, transcript)

    if config.FISH_VOICE_DIR and os.path.isdir(config.FISH_VOICE_DIR):
        cfg_path = os.path.join(config.FISH_VOICE_DIR, "config.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                for entry in cfg.get("references", []):
                    a = os.path.join(config.FISH_VOICE_DIR, entry["audio"])
                    t_field = entry.get("text", "")
                    if not t_field and entry.get("text_file"):
                        t_field = open(
                            os.path.join(config.FISH_VOICE_DIR, entry["text_file"]),
                            encoding="utf-8",
                        ).read().strip()
                    refs.append((a, t_field))
            except (OSError, json.JSONDecodeError, KeyError) as e:
                _log(f"voice config.json malformed ({e}); falling back to auto-scan")
                refs = []

        if not refs:
            # Auto-scan: every reference*.wav with matching .txt.
            for name in sorted(os.listdir(config.FISH_VOICE_DIR)):
                if not name.endswith(".wav") or not name.startswith("reference"):
                    continue
                wav = os.path.join(config.FISH_VOICE_DIR, name)
                txt = os.path.join(config.FISH_VOICE_DIR, name[:-4] + ".txt")
                t = ""
                if os.path.isfile(txt):
                    try:
                        with open(txt, encoding="utf-8") as f:
                            t = f.read().strip()
                    except OSError:
                        pass
                refs.append((wav, t))

    elif config.FISH_REFERENCE_VOICE and os.path.isfile(config.FISH_REFERENCE_VOICE):
        refs.append((config.FISH_REFERENCE_VOICE, config.FISH_REFERENCE_TEXT or ""))

    out: list[dict] = []
    for wav, t in refs:
        try:
            with open(wav, "rb") as f:
                out.append({
                    "audio": base64.b64encode(f.read()).decode("ascii"),
                    "text": t,
                })
        except OSError as e:
            _log(f"skipping ref {wav}: {e}")
    if out:
        _log(f"loaded {len(out)} voice reference(s)")
    return out


def _load_synth_params() -> dict:
    """Read synthesis params from voices/<dir>/config.json if present,
    falling back to v3-tuned defaults (the configuration that produced
    the best zh+en balance during Listen-Claude voice cloning tests)."""
    defaults = {
        "format": "wav",
        "chunk_length": 100,
        "max_new_tokens": 800,
        "top_p": 0.7,
        "repetition_penalty": 1.2,
        "temperature": 0.4,
    }
    if config.FISH_VOICE_DIR and os.path.isdir(config.FISH_VOICE_DIR):
        cfg_path = os.path.join(config.FISH_VOICE_DIR, "config.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                synth = cfg.get("synthesis", {})
                # Only honor known keys; ignore extras.
                for k in defaults:
                    if k in synth:
                        defaults[k] = synth[k]
            except (OSError, json.JSONDecodeError):
                pass
    return defaults


# ---------------------------------------------------------------------------
# Synthesis request.

def _request_synthesis(text: str) -> bytes | None:
    """POST text to the server, return WAV bytes on success or None on
    any failure. Bundles the configured voice references."""
    # Empirical: the digit-to-Chinese + English-spacing preprocessor
    # _looked_ helpful in isolated tests but actually degrades production
    # quality. Live Listen-Claude text mentions PIDs / ports / sizes
    # ("15416", "7867") which the digit converter expands to long Chinese
    # readings ("一萬五千四百一十六") that fish-speech 1.5 struggles to
    # generate cleanly. Sending raw text matches the configuration that
    # produced the test-clone WAVs the user judged best.
    body = {"text": text, **_load_synth_params()}

    refs = _load_voice_refs()
    if refs:
        body["references"] = refs

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
