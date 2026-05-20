"""Runtime configuration loaded from .env."""

import os
import tempfile

from dotenv import load_dotenv

load_dotenv()

import sys
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# TTS engine. Free / no-setup options first:
#   "edge"       — Microsoft Edge cloud (default in .env.example). No GPU.
#   "system"     — OS built-in (macOS say / Win SAPI / Linux espeak). No GPU.
#   "piper"      — local Piper TTS (CPU ONNX). Requires `piper-tts` + voice.
#   "elevenlabs" — paid cloud, top quality. No GPU.
#   "fish"       — local fish-speech (CUDA recommended). Native Chinese
#                  / English code-switching + voice cloning. Auto-falls
#                  back to TTS_FALLBACK_ENGINE if CUDA / server / model
#                  is unavailable — safe to enable on machines without GPU.
TTS_ENGINE = os.getenv("TTS_ENGINE", "system").lower()

# Engine to use when the primary engine fails (e.g. fish-speech with no
# CUDA / no model / server crash). Never set this to "fish" itself —
# fish.py guards against that, but keeping it as a cloud / CPU engine
# makes the intent obvious.
TTS_FALLBACK_ENGINE = os.getenv("TTS_FALLBACK_ENGINE", "edge").lower()

# Voice identifier — interpretation depends on the engine:
#   system + macOS: voice name (e.g. "Mei-Jia", "Tingting"); `say -v '?'`
#   system + Windows: voice name (e.g. "Microsoft Yating Desktop")
#   piper: path to .onnx file, or short name resolved under PIPER_VOICES_DIR
TTS_VOICE = os.getenv("TTS_VOICE", "")

# Reading mode:
#   "llm"       — call `claude -p` (Haiku by default) to rewrite the
#                 response as a natural spoken summary, free of markdown
#                 / symbols / code. Best quality, costs ~$0.001 per
#                 response, adds ~3-8s latency. Falls back to "progress"
#                 if the CLI is missing or fails.
#   "progress"  — opening sentence + first ~4 bullet items (heuristic).
#   "full"      — read the entire last assistant message.
#   "first"     — only the first paragraph.
#   "summary"   — every paragraph's first sentence + headings.
TTS_MODE = os.getenv("TTS_MODE", "progress")

# When TTS_MODE=llm, which model `claude -p` should call.
TTS_LLM_MODEL = os.getenv("TTS_LLM_MODEL", "claude-haiku-4-5")
TTS_LLM_TIMEOUT_SEC = float(os.getenv("TTS_LLM_TIMEOUT_SEC", "60"))

# Skip TTS if message has fewer words than this (avoid reading "ok").
TTS_MIN_WORDS = int(os.getenv("TTS_MIN_WORDS", "20"))

# Maximum characters to send to TTS (truncate longer messages).
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "500"))

# Words per minute roughly; engine-specific mapping in tts/<engine>.py.
TTS_RATE = int(os.getenv("TTS_RATE", "200"))

# Master switch — set to "0" to disable TTS without uninstalling.
TTS_ENABLED = os.getenv("TTS_ENABLED", "1") == "1"

# Prepend the project / window name (e.g. "Kaikou-Claude:") before the
# spoken text so you know which background window is talking. Useful when
# multiple Claude sessions are open. Set to 0 to disable.
ANNOUNCE_PROJECT = os.getenv("ANNOUNCE_PROJECT", "1") == "1"

# Worker lock — held by whichever process is currently draining the
# spoken queue. Other hooks enqueue their item and either become the
# worker themselves (if the lock is free) or wait for the current worker
# to pick up their file. Avoids overlapping audio AND dropped messages
# when multiple Claude windows finish at roughly the same time.
LOCK_PATH = os.path.join(tempfile.gettempdir(), "listen-claude.lock")
LOCK_STALE_SEC = float(os.getenv("LOCK_STALE_SEC", "60"))

# Pending TTS requests live as JSON files in this directory; filenames
# are nanosecond timestamps so plain lexicographic sort = FIFO order.
QUEUE_DIR = os.path.join(tempfile.gettempdir(), "listen-claude-queue")

# After the queue empties, the worker keeps the lock for this long
# before releasing it. Lets late-arriving requests be picked up by the
# current worker rather than handing off to a new process (which would
# briefly delay playback and risk a race during handoff).
WORKER_GRACE_SEC = float(os.getenv("WORKER_GRACE_SEC", "2.0"))

# Items older than this (by their wall-clock enqueue time) are dropped
# without speaking. Guards against the worker replaying stale text that
# was orphaned by an earlier crash hours/days ago.
QUEUE_MAX_AGE_SEC = float(os.getenv("QUEUE_MAX_AGE_SEC", "300"))

# Runtime toggle marker — if this file exists, TTS is disabled regardless
# of TTS_ENABLED. Created/removed by scripts/toggle.{ps1,sh} for fast on/off
# without editing .env.
TOGGLE_MARKER = os.path.join(tempfile.gettempdir(), "listen-claude.disabled")


def is_enabled() -> bool:
    if not TTS_ENABLED:
        return False
    if os.path.exists(TOGGLE_MARKER):
        return False
    return True

# Piper-specific: directory holding .onnx and .onnx.json voice files.
PIPER_VOICES_DIR = os.getenv(
    "PIPER_VOICES_DIR",
    os.path.expanduser("~/.cache/piper-voices"),
)

# --- fish-speech (TTS_ENGINE=fish) ---------------------------------------
# The fish-speech HTTP API server runs as a persistent local subprocess so
# we pay the ~10 s model-load cost only once. The Stop hook talks to it
# over loopback; ports / paths below are tuned for that contract.

# Listen address of the local fish-speech API server.
FISH_HOST = os.getenv("FISH_HOST", "127.0.0.1")
FISH_PORT = int(os.getenv("FISH_PORT", "7867"))

# Where downloaded fish-speech checkpoints live. The install script writes
# weights here; the engine + server look here when starting up.
FISH_MODEL_DIR = os.getenv(
    "FISH_MODEL_DIR",
    os.path.expanduser("~/.cache/fish-speech"),
)

# Voice profile directory. Drop reference WAVs and matching .txt
# transcripts here (e.g. voices/ig-demo/reference.wav + reference.txt,
# voices/ig-demo/reference-b.wav + reference-b.txt, ...). Optionally
# include voices/<name>/config.json to pin synthesis params + which
# refs to use. Empty = use fish-speech's built-in preset voice.
FISH_VOICE_DIR = os.getenv("FISH_VOICE_DIR", "")

# Legacy single-reference mode. Still honored if FISH_VOICE_DIR is empty
# — falls back to a single ref + transcript pair.
FISH_REFERENCE_VOICE = os.getenv("FISH_REFERENCE_VOICE", "")
FISH_REFERENCE_TEXT = os.getenv("FISH_REFERENCE_TEXT", "")

# How long to wait for the server's /docs endpoint to come up after we
# spawn it. Fish-speech's first import (torch + transformers) is heavy;
# 60 s is conservative for a cold start on a typical laptop GPU.
FISH_STARTUP_TIMEOUT_SEC = float(os.getenv("FISH_STARTUP_TIMEOUT_SEC", "60"))

# Per-request synthesis timeout. Fish-speech 1.5 without torch.compile
# runs at ~3 tokens/sec on a single 8 GB GPU, so an 800-token summary
# can legitimately take ~4 minutes. Set this generously to avoid the
# client tearing down a slow-but-working synth request.
FISH_SYNTH_TIMEOUT_SEC = float(os.getenv("FISH_SYNTH_TIMEOUT_SEC", "240"))

# After this many seconds of idle, the server frees VRAM and exits.
# Subsequent requests will pay the cold-start cost again.
FISH_IDLE_TIMEOUT_SEC = float(os.getenv("FISH_IDLE_TIMEOUT_SEC", "600"))

# Force the server to run on CPU even when CUDA is present. Mainly for
# debugging fallback behavior; CPU inference is ~10-20x slower so it's
# rarely useful in production.
FISH_FORCE_CPU = os.getenv("FISH_FORCE_CPU", "0") == "1"

# Override command used to launch the fish-speech API server (advanced).
# Leave empty to use the default `python -m tools.api_server ...` form
# computed inside fish.py / fish_server.py. Pass a string and we'll
# split it via shlex.
FISH_SERVER_CMD = os.getenv("FISH_SERVER_CMD", "")

# -------------------------------------------------------------------------

LOG_PATH = os.path.join(tempfile.gettempdir(), "listen-claude.log")
