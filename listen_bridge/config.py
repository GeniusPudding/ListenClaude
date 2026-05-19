"""Runtime configuration loaded from .env."""

import os
import tempfile

from dotenv import load_dotenv

load_dotenv()

import sys
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# TTS engine: "system" (built-in: macOS say / Win SAPI), "piper" (local
# Piper TTS, requires the piper-tts pip package and a downloaded voice).
TTS_ENGINE = os.getenv("TTS_ENGINE", "system").lower()

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

# Path of a lock file used to skip TTS when another instance is already
# speaking — avoids overlapping audio when multiple Claude windows finish
# at roughly the same time.
LOCK_PATH = os.path.join(tempfile.gettempdir(), "listen-claude.lock")
LOCK_STALE_SEC = float(os.getenv("LOCK_STALE_SEC", "60"))

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

LOG_PATH = os.path.join(tempfile.gettempdir(), "listen-claude.log")
