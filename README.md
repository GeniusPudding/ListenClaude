[English](README.md) · [繁體中文](README.zh-TW.md)

# Listen-Claude（聽聲即克）

Hear Claude Code's responses as audio. Triggered automatically when Claude finishes responding — a parallel input channel that lets you *read and listen at the same time* to expand human–AI bandwidth.

Companion to [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude) (voice → Claude). This project is Claude → voice.

## Features

- **Auto-triggered** by Claude Code's `Stop` hook — zero manual interaction.
- **Five TTS engines** — free neural (Edge), OS built-in, fully offline (Piper), premium cloud (ElevenLabs), or local GPU with native zh/en code-switching + voice cloning (fish-speech).
- **Runtime mode switch** — flip between brief and detailed spoken replies via `/listen <mode>`.
- **Skip-short threshold** — won't read trivial "ok" responses.
- **FIFO queue across windows** — every Claude session's summary is spoken in turn; nothing is dropped when several windows finish at once.

## Platform support

| Platform | Default engine | Status | Notes |
|----------|----------------|--------|-------|
| Windows  | Edge TTS | **Stable** | SAPI also available via `system` engine. |
| macOS    | Edge TTS | **Stable** | `say` voices available via `system`. |
| Linux    | Edge TTS | **Stable** | Install `mpg123` for MP3 playback (Edge / ElevenLabs). |

## Install

One command on every platform (clone + run install):

```bash
git clone https://github.com/GeniusPudding/Listen-Claude.git
cd Listen-Claude
.\install.ps1   # Windows
./install.sh    # macOS / Linux
```

The installer:

1. Creates a local `.venv` and installs Python deps (including `edge-tts`).
2. Writes a default `.env` (only if missing).
3. Registers a `Stop` hook in `~/.claude/settings.json` that invokes the venv Python directly (no shell wrapper, preserves stdin bytes).
4. Installs `/listen` and `/choose-voice` skills to `~/.claude/skills/`.
5. Optionally downloads a Piper voice if `PIPER_VOICE` env var is set during install.

Idempotent — re-run any time to upgrade or repair.

## Usage

### Control — `/listen` skill

One skill controls both on/off and reading length. All changes take effect on the next Claude response; no restart.

**On/off:**

```
/listen           → toggle current state
/listen on        → enable
/listen off       → disable
/listen status    → report state
```

**Reading mode** (how each response is rewritten for speech):

```
/listen llm       → Claude-rewritten natural spoken summary (~$0.001 / response)
/listen brief     → opening paragraph only (heuristic)
/listen progress  → opening + first ~4 bullets (default, heuristic)
/listen summary   → first sentence per paragraph + headings (heuristic)
/listen detailed  → full response
/listen mode      → report current mode
```

`/listen llm` (alias `smart`) calls the local `claude -p` CLI (Haiku by default) to rewrite each response into a natural spoken summary — free of markdown, code blocks, URLs, etc. Adds ~3–8 s latency before audio starts; falls back to `progress` if the CLI is missing or fails.

Equivalent script (skill calls this under the hood):

```bash
.\scripts\toggle.ps1  <arg>   # Windows
bash scripts/toggle.sh <arg>  # macOS / Linux
```

On/off uses a marker file (`$TMPDIR/listen-claude.disabled`); modes are written to `.env`.

### Choosing a voice — `/choose-voice` skill

```
/choose-voice                            → list options
/choose-voice list edge Chinese voices
/choose-voice use zh-TW-HsiaoChenNeural
/choose-voice what voice am I using
```

The skill autodetects the engine from the voice ID format (`zh-TW-…Neural` → Edge, `zh_CN-…` → Piper, 20-char alphanumeric → ElevenLabs, anything else → system).

#### Engines at a glance

| Engine | Cost | Quality | Setup | Pick when |
|--------|------|---------|-------|-----------|
| **`edge`** (default) | Free | High (neural) | Automatic | Best default — start here |
| `system` | Free | Basic | None | No network egress, smallest footprint |
| `piper` | Free | High (neural) | Manual model download | Fully offline / air-gapped |
| `elevenlabs` | Paid | Top | API key | Studio-grade voice quality |
| `fish` | Free* | Top | `scripts/install-fish-speech` | Local GPU + native zh/en code-switching + voice cloning |

\* `fish` is free to run but downloads ~2 GB of model weights and needs CUDA for usable speed. Auto-falls back to `TTS_FALLBACK_ENGINE` (default `edge`) when CUDA / fish-speech / the local server is unavailable — safe to enable on no-GPU machines.

**Edge TTS** — popular Chinese voices: `zh-TW-HsiaoChenNeural` (TW female, default), `zh-TW-YunJheNeural` (TW male), `zh-CN-XiaoxiaoNeural` (CN female), `yue-HK-WanLungNeural` (Cantonese). Full list: `.venv/bin/edge-tts --list-voices`.

**System TTS** — `Mei-Jia` (macOS TW), `Tingting` (macOS CN), `Microsoft Yating Desktop` (Win TW). Set `TTS_ENGINE=system`.

**Piper** — download a voice then switch:

```bash
.\scripts\install-piper-voice.ps1 zh_CN-huayan-medium  ;  .\scripts\set-voice.ps1 zh_CN-huayan-medium piper   # Windows
bash scripts/install-piper-voice.sh zh_CN-huayan-medium && bash scripts/set-voice.sh zh_CN-huayan-medium piper  # macOS / Linux
```

Samples: <https://rhasspy.github.io/piper-samples/>. Catalog: <https://huggingface.co/rhasspy/piper-voices/tree/main>.

**ElevenLabs** — copy a voice ID from <https://elevenlabs.io/app/voice-library>, then:

```
TTS_ENGINE=elevenlabs
TTS_VOICE=<voice_id>
ELEVENLABS_API_KEY=<your_key>
```

**fish-speech (GPU)** — local high-quality TTS with native Chinese/English code-switching and zero-shot voice cloning. Install (one-time):

```bash
.\scripts\install-fish-speech.ps1   # Windows
bash scripts/install-fish-speech.sh # macOS / Linux
```

The script detects CUDA, installs the right PyTorch wheel (or CPU-only on no-GPU machines), pulls `fish-speech` from PyPI, and downloads the `fish-speech-1.5` checkpoints (~2 GB) to `~/.cache/fish-speech`. Then in `.env`:

```
TTS_ENGINE=fish
TTS_FALLBACK_ENGINE=edge        # what to use when CUDA / server unavailable
# Optional voice cloning:
FISH_REFERENCE_VOICE=voices/myvoice.wav   # 10-30 s, single speaker, clean
FISH_REFERENCE_TEXT=請輸入這段參考錄音的逐字稿
```

How it works: the first response after a cold machine spawns a persistent local HTTP server (`python -m tools.api_server`) that holds the model in VRAM. Cold start ~10 s; each subsequent response is ~1–2 s of synthesis. The server self-terminates after `FISH_IDLE_TIMEOUT_SEC` (default 600 s) of inactivity to free VRAM.

If anything along the chain breaks (no CUDA, fish-speech not installed, model missing, server crashed, network error), `fish.py` silently delegates to `TTS_FALLBACK_ENGINE` so audio always plays — set `TTS_ENGINE=fish` in `.env` and ship the repo to a no-GPU teammate and it'll just behave like Edge for them.

## Uninstall

```bash
.\uninstall.ps1   # Windows
./uninstall.sh    # macOS / Linux
```

Removes the Stop hook from `~/.claude/settings.json`. Repo files stay on disk.

---

## Configuration (`.env`)

| Variable | Default | Notes |
|----------|---------|-------|
| `TTS_ENABLED` | `1` | `0` disables without uninstalling. |
| `TTS_ENGINE` | `edge` | `edge`, `system`, `piper`, `elevenlabs`, or `fish`. |
| `TTS_FALLBACK_ENGINE` | `edge` | Engine used when the primary fails (e.g. `fish` with no CUDA). Must not be `fish`. |
| `TTS_VOICE` | `zh-TW-HsiaoChenNeural` | Engine-specific voice ID. |
| `TTS_MODE` | `progress` | `llm`, `progress`, `first`, `summary`, or `full`. Switchable at runtime via `/listen <mode>`. |
| `TTS_LLM_MODEL` | `claude-haiku-4-5` | Model `claude -p` calls when `TTS_MODE=llm`. |
| `TTS_LLM_TIMEOUT_SEC` | `60` | Give up on the LLM rewrite after this many seconds and fall back to `progress`. |
| `TTS_MIN_WORDS` | `20` | Skip TTS if response shorter than this. |
| `TTS_MAX_CHARS` | `500` | Truncate longer responses. |
| `TTS_RATE` | `200` | Rough words-per-minute (engine-specific mapping). |
| `ANNOUNCE_PROJECT` | `1` | Prepend project / window name before spoken text. |
| `PIPER_VOICES_DIR` | `~/.cache/piper-voices` | Piper voice files location. |
| `FISH_MODEL_DIR` | `~/.cache/fish-speech` | Where fish-speech checkpoints live. |
| `FISH_HOST` / `FISH_PORT` | `127.0.0.1` / `7867` | Loopback address of the auto-started fish-speech API server. |
| `FISH_REFERENCE_VOICE` | *(empty)* | Optional WAV/MP3 path for zero-shot voice cloning. |
| `FISH_REFERENCE_TEXT` | *(empty)* | Transcript of the reference voice (improves clone quality). |
| `FISH_STARTUP_TIMEOUT_SEC` | `60` | Cold-start budget for the fish-speech server. |
| `FISH_SYNTH_TIMEOUT_SEC` | `30` | Per-request synthesis timeout. |
| `FISH_IDLE_TIMEOUT_SEC` | `600` | Server exits after this much idle to free VRAM. |
| `FISH_FORCE_CPU` | `0` | Force CPU even when CUDA is available (debugging). |
| `FISH_SERVER_CMD` | *(empty)* | Advanced: full override of the server launch command. |

## How it works

```
Claude Code finishes responding
        ↓ Stop hook fires
scripts/stop_hook_entry.py receives JSON on stdin
        ↓
listen_bridge.runner:
  1. Parse last assistant message from the hook payload
  2. Apply TTS_MODE (llm / progress / brief / summary / full) — for `llm`,
     call `claude -p` to rewrite the response as a natural spoken summary
  3. Strip code blocks and markdown noise; truncate to TTS_MAX_CHARS
  4. Enqueue the resolved text in $TMPDIR/listen-claude-queue/
        (filename = ns timestamp, so plain sort = FIFO across windows)
  5. Try to atomically claim the worker lock:
        - Claimed → drain the queue in order, speaking each item; release
          after the queue stays empty for WORKER_GRACE_SEC.
        - Already held → wait until our file is consumed by the current
          worker, or the lock goes stale (LOCK_STALE_SEC) and we take over.
  6. TTS_ENGINE plays the audio
        ↓
TTS engine plays audio in the background — never blocks Claude Code.
```

## Logs

`%TEMP%\listen-claude.log` (Windows) or `$TMPDIR/listen-claude.log` (Unix).

## Coexistence with other Claude Code plugins

Listen-Claude only adds a `Stop` hook. It plays nicely with any other plugin that uses `SessionStart` / `SessionEnd` / `PreToolUse` etc. — including [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude) (Chinese voice input). The `patch_settings.py` script matches its own entries by a known substring so re-install / uninstall never touches unrelated hooks.
