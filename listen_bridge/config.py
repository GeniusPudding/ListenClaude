"""Runtime configuration loaded from .env."""

import os
import tempfile

from dotenv import load_dotenv

# Always resolve .env relative to THIS file (the Listen-Claude repo
# root), NOT the cwd of whoever invoked us. The Stop hook fires from
# each Claude Code conversation's own project dir, so plain
# `load_dotenv()` would only find an .env that happens to live in
# that project's tree — meaning every other window's hook silently
# falls back to defaults, regardless of what we wrote to our .env.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LISTEN_CLAUDE_ENV = os.path.join(_REPO_ROOT, ".env")
load_dotenv(_LISTEN_CLAUDE_ENV)


def _from_repo_root(p: str) -> str:
    """Resolve a path from the .env relative to the Listen-Claude repo
    root, not the cwd of whoever invoked us. Each Claude Code window's
    Stop hook runs from its OWN project directory, so a relative path
    like 'voices/ig-demo/reference-c.wav' would otherwise be looked up
    inside that other project's tree (and fail). Absolute paths and
    empty strings pass through unchanged."""
    if not p or os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(_REPO_ROOT, p))

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
#   "gptsovits"  — local GPT-SoVITS (CUDA + fine-tuned weights). Best
#                  voice cloning for the trained speaker, but the model
#                  inherits the speaker's language (poor English if
#                  trained on Chinese-only).
#   "auto"       — per-utterance router. Counts ASCII-letter ratio; if
#                  above TTS_AUTO_ENGLISH_THRESHOLD the utterance goes
#                  to TTS_AUTO_EN_ENGINE (default edge, reliable English);
#                  otherwise to TTS_AUTO_ZH_ENGINE (default gptsovits,
#                  cloned voice). Best of both worlds for mixed daily use.
TTS_ENGINE = os.getenv("TTS_ENGINE", "system").lower()

# Auto-router knobs. ASCII-letter ratio = (a-zA-Z chars) / (total chars).
# 0.15 means "if > 15% of the text is English letters, route to the
# English-strong engine". Tune per personal preference.
TTS_AUTO_ENGLISH_THRESHOLD = float(os.getenv("TTS_AUTO_ENGLISH_THRESHOLD", "0.15"))
TTS_AUTO_EN_ENGINE = os.getenv("TTS_AUTO_EN_ENGINE", "edge").lower()
TTS_AUTO_ZH_ENGINE = os.getenv("TTS_AUTO_ZH_ENGINE", "gptsovits").lower()

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

# Template for how the project announcement is joined to the body.
# Available placeholders: {project} and {text}. Defaults to a plain
# `"<project>: <text>"`. Cloned-voice engines (gptsovits) often elide
# English-only project names because the fine-tune was Chinese-only —
# setting this to e.g. "視窗 {project}:{text}" prepends a reliably
# pronounceable Chinese token (視窗 = "window") that wakes the model
# up before the English name is attempted. Pair with PROJECT_ALIASES
# (below) to transliterate the names themselves.
ANNOUNCE_FORMAT = os.getenv("ANNOUNCE_FORMAT", "{project}: {text}")

# Per-project Chinese aliases. JSON file mapping
#   {"Listen-Claude": "聽小爪", "MandpopDataset": "華語資料集"}
# Used at announcement time: an aliased name is substituted for the raw
# cwd basename before {project} is rendered into ANNOUNCE_FORMAT, so
# cloned voices that can only pronounce Chinese reliably can still call
# out which window is speaking. Missing file = no substitutions. The
# file lives under voices/ by default (alongside profiles) but the path
# is configurable.
PROJECT_ALIASES_FILE = _from_repo_root(
    os.getenv("PROJECT_ALIASES_FILE", os.path.join("voices", "project-aliases.json"))
)


def project_alias(name: str) -> str:
    """Return the Chinese alias registered in PROJECT_ALIASES_FILE for
    this project name, falling back to the original name when there's
    no entry (or the file is missing / malformed)."""
    if not name:
        return name
    try:
        import json as _json
        with open(PROJECT_ALIASES_FILE, encoding="utf-8") as f:
            aliases = _json.load(f)
        return str(aliases.get(name, name))
    except (OSError, ValueError):
        return name

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
FISH_VOICE_DIR = _from_repo_root(os.getenv("FISH_VOICE_DIR", ""))

# Legacy single-reference mode. Still honored if FISH_VOICE_DIR is empty
# — falls back to a single ref + transcript pair.
FISH_REFERENCE_VOICE = _from_repo_root(os.getenv("FISH_REFERENCE_VOICE", ""))
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

# --- GPT-SoVITS (TTS_ENGINE=gptsovits) -----------------------------------
# GPT-SoVITS runs in its own Py3.10/3.12 venv (.venv-gptsovits/) because
# its torch + lightning + funasr deps conflict with the main venv's
# Py3.13 stack. The api_v2 server is a long-lived subprocess that loads
# fine-tuned ig-girl checkpoints + holds them in VRAM across requests.

# Loopback bind for the api_v2 server.
GPTSOVITS_HOST = os.getenv("GPTSOVITS_HOST", "127.0.0.1")
GPTSOVITS_PORT = int(os.getenv("GPTSOVITS_PORT", "9880"))

# Python interpreter inside .venv-gptsovits/ that has the GPT-SoVITS deps.
GPTSOVITS_PYTHON = os.getenv(
    "GPTSOVITS_PYTHON",
    os.path.join(_REPO_ROOT, ".venv-gptsovits", "Scripts", "python.exe")
    if IS_WIN
    else os.path.join(_REPO_ROOT, ".venv-gptsovits", "bin", "python"),
)

# Cloned GPT-SoVITS source dir (api_v2.py + GPT_SoVITS/ package + the
# downloaded base BERT / HuBERT under GPT_SoVITS/pretrained_models/).
GPTSOVITS_SOURCE_DIR = os.getenv(
    "GPTSOVITS_SOURCE_DIR",
    os.path.expanduser("~/.cache/gpt-sovits-source"),
)
GPTSOVITS_API_SCRIPT = os.path.join(GPTSOVITS_SOURCE_DIR, "api_v2.py")

# Fine-tuned weights from our `voices/ig-demo/train-gptsovits.py` run.
_VOICE_TRAIN_DIR = os.path.join(_REPO_ROOT, "voices", "ig-demo", "gptsovits-train")
GPTSOVITS_GPT_WEIGHTS = os.getenv(
    "GPTSOVITS_GPT_WEIGHTS",
    os.path.join(_VOICE_TRAIN_DIR, "GPT_weights", "ig-girl-e15.ckpt"),
)
GPTSOVITS_SOVITS_WEIGHTS = os.getenv(
    "GPTSOVITS_SOVITS_WEIGHTS",
    # Production uses the v2 BASE SoVITS, not the fine-tuned one. The
    # fine-tune overfit with only 49 segments and produced garbled audio
    # at inference; base + 7.9 s reference gives cleaner zero-shot voice
    # cloning. The fine-tuned SoVITS weights are still on disk for
    # future re-training experiments.
    os.path.join(
        os.path.expanduser("~/.cache/gpt-sovits-source"),
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    ),
)

# tts_infer.yaml — one per voice profile (lives next to the weights)
# pointing api_v2 at our fine-tuned models + the shared BERT/HuBERT/G2P
# bases in GPT_SoVITS/pretrained_models/.
GPTSOVITS_TTS_INFER_YAML = os.getenv(
    "GPTSOVITS_TTS_INFER_YAML",
    os.path.join(_VOICE_TRAIN_DIR, "tts_infer.yaml"),
)

# Voice profile name (looks up voices/<name>/profile.json). When set,
# the profile's `engines.gptsovits` block overrides the GPTSOVITS_*
# fields below — that's how `scripts/clone-voice activate <name>`
# switches the active cloned voice without touching code.
GPTSOVITS_VOICE_PROFILE = os.getenv("GPTSOVITS_VOICE_PROFILE", "")

# Reference audio + transcript for per-request voice conditioning.
# When empty, gptsovits.py falls back to voices/<FISH_VOICE_DIR>/reference.*
# so a single voice profile drives both gptsovits and fish engines.
GPTSOVITS_REFERENCE_VOICE = _from_repo_root(os.getenv("GPTSOVITS_REFERENCE_VOICE", ""))
GPTSOVITS_REFERENCE_TEXT = os.getenv("GPTSOVITS_REFERENCE_TEXT", "")

# Language tags passed in each /tts request.
GPTSOVITS_TEXT_LANG = os.getenv("GPTSOVITS_TEXT_LANG", "zh")
GPTSOVITS_PROMPT_LANG = os.getenv("GPTSOVITS_PROMPT_LANG", "zh")

# api_v2 cold-start is heavier than fish-speech (BERT + HuBERT + GPT +
# SoVITS all loaded together).
GPTSOVITS_STARTUP_TIMEOUT_SEC = float(os.getenv("GPTSOVITS_STARTUP_TIMEOUT_SEC", "120"))
GPTSOVITS_SYNTH_TIMEOUT_SEC = float(os.getenv("GPTSOVITS_SYNTH_TIMEOUT_SEC", "180"))

# Synthesis sampling knobs (all overridable via env). The defaults are
# what produced the most natural output during voice cloning trials
# on the ig-girl voice — start here and tweak per voice profile.
GPTSOVITS_TOP_K = int(os.getenv("GPTSOVITS_TOP_K", "15"))
GPTSOVITS_TOP_P = float(os.getenv("GPTSOVITS_TOP_P", "0.7"))
GPTSOVITS_TEMPERATURE = float(os.getenv("GPTSOVITS_TEMPERATURE", "0.7"))
GPTSOVITS_REPETITION_PENALTY = float(os.getenv("GPTSOVITS_REPETITION_PENALTY", "1.35"))
# Speed factor: 1.0 = original pace of the reference, <1.0 = slower,
# >1.0 = faster. Fine-tune on small data tends to read too fast; 0.85
# is a good starting point for clarity.
GPTSOVITS_SPEED_FACTOR = float(os.getenv("GPTSOVITS_SPEED_FACTOR", "0.85"))
# Text split method: cut0 = whole text in one shot (smoothest),
# cut1 = every ~4 sentences, cut2 = every ~50 chars, cut3 = on CJK
# punctuation, cut4 = on ASCII, cut5 = on both. For short summaries
# cut0 reads the most natural.
GPTSOVITS_TEXT_SPLIT = os.getenv("GPTSOVITS_TEXT_SPLIT", "cut0")
# Pause inserted between fragments when text_split is not cut0.
GPTSOVITS_FRAGMENT_INTERVAL = float(os.getenv("GPTSOVITS_FRAGMENT_INTERVAL", "0.3"))

# Advanced: full override of the server launch command.
GPTSOVITS_SERVER_CMD = os.getenv("GPTSOVITS_SERVER_CMD", "")
# -------------------------------------------------------------------------

# --- Notification hook (Yes/No permission prompts) ----------------------
# Claude Code's Notification hook fires when something needs the user's
# attention — most usefully on tool-permission Yes/No prompts. When a
# notification comes in, the runner enqueues a short spoken prompt
# (default 「視窗 <project>:需要確認」) into the same FIFO the Stop hook
# uses, so multiple windows still play in order.

# Only notifications whose `message` field contains any of these
# substrings (case-insensitive) are spoken. Idle notifications etc.
# are filtered out so the speaker doesn't shout at you when you walk
# away from the desk.
NOTIFY_KEYWORDS = tuple(
    s.strip().lower()
    for s in os.getenv("NOTIFY_KEYWORDS", "permission,needs your").split(",")
    if s.strip()
)

# Short body spoken when a permission notification fires. Combined with
# NOTIFY_FORMAT to produce e.g. 「視窗 聽小爪,需要你確認一下喔。」.
# The body intentionally ends in 「。」 — autoregressive TTS models that
# never see a final-punctuation token tend to either emit pure breath
# (no synthesized speech at all) or ramble past the actual text. The
# default phrasing is also long enough to give the model time to enter
# its rhythm; very short bodies (~10 chars) collapse to noise.
NOTIFY_BODY = os.getenv("NOTIFY_BODY", "需要你確認一下喔。")

# Format used when joining the project name and NOTIFY_BODY into the
# spoken string. Distinct from ANNOUNCE_FORMAT (which the Stop hook
# uses) because notifications are short enough that the project name
# can get swallowed in the autoregressive warmup — repeating the name
# at both ends gives a second chance to catch it.
NOTIFY_FORMAT = os.getenv(
    "NOTIFY_FORMAT", "{project},視窗 {project},{text}"
)

# Engine to use for spoken notifications. Defaults to "edge" rather
# than TTS_ENGINE so that the voice-clone setup (which is tuned for
# the long-text Stop-hook readback) doesn't degrade the short, urgent
# Yes/No prompts. Edge handles short Chinese + English mixed text
# cleanly out of the box and never produces the "all breath / no
# speech" collapse we saw with the cloned voice on 4-character bodies.
# Set to "auto" to honor the main TTS_ENGINE for notifications too.
NOTIFY_ENGINE = os.getenv("NOTIFY_ENGINE", "edge").lower()

# Per-project dedupe window. If the same project triggers another
# notification within this many seconds of the previous spoken one, we
# skip it — covers the case where you click 'n' a few times in quick
# succession and Claude Code re-prompts.
NOTIFY_DEDUPE_SEC = float(os.getenv("NOTIFY_DEDUPE_SEC", "10"))

# Where the per-project "last spoken" timestamps live (just empty files
# whose mtime is what we check). Lives next to the queue dir so it
# shares the same cleanup story.
NOTIFY_STATE_DIR = os.path.join(tempfile.gettempdir(), "listen-claude-notify")

# Per-cwd silence: if a marker file exists under here whose name
# matches the firing project's directory, skip the notification. Used
# by users who run a particular project in Claude Code auto-accept
# mode — every auto-accepted tool still fires a Notification payload
# we'd otherwise pass through the filter and speak, which is noise
# when the prompts aren't actually blocking the user.
NOTIFY_DISABLED_DIR = os.path.join(
    tempfile.gettempdir(), "listen-claude-notify-disabled"
)


def notify_is_disabled_for(cwd: str) -> bool:
    """True if the user has silenced notifications for this project
    directory via `scripts/toggle notify off`."""
    if not cwd:
        return False
    name = os.path.basename(cwd.rstrip("/\\")) or cwd
    safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:120]
    return os.path.exists(os.path.join(NOTIFY_DISABLED_DIR, safe + ".flag"))

# Per-session activity title (used by Notification to say "在做 X 那個
# 視窗" instead of just the project name, so multiple windows in the
# same project stay distinguishable by ear). Written by the
# UserPromptSubmit hook, read by notification_main.
SESSION_STATE_DIR = os.path.join(tempfile.gettempdir(), "listen-claude-sessions")
SESSION_SUMMARY_MAX_CHARS = int(os.getenv("SESSION_SUMMARY_MAX_CHARS", "30"))

# Format used when a session title is available. {summary} is the
# captured user prompt headline, {project} is the directory name, and
# {text} is NOTIFY_BODY. Falls back to NOTIFY_FORMAT (project-only)
# when no session title has been recorded for the firing session.
NOTIFY_FORMAT_WITH_SUMMARY = os.getenv(
    "NOTIFY_FORMAT_WITH_SUMMARY",
    "在做 {summary} 的視窗,{text}",
)
# -------------------------------------------------------------------------

LOG_PATH = os.path.join(tempfile.gettempdir(), "listen-claude.log")
