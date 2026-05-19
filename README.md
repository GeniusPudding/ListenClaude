[English](README.md) · [繁體中文](README.zh-TW.md)

# Listen-Claude（聽聲即克）

Hear Claude Code's responses as audio. Triggered automatically when Claude finishes responding — a parallel input channel that lets you *read and listen at the same time* to expand human–AI bandwidth.

Companion to [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude) (voice → Claude). This project is Claude → voice.

## Features

- **Auto-triggered** by Claude Code's `Stop` hook — zero manual interaction.
- **Four TTS engines** — free neural (Edge), OS built-in, fully offline (Piper), or premium cloud (ElevenLabs).
- **Runtime mode switch** — flip between brief and detailed spoken replies via `/listen <mode>`.
- **Skip-short threshold** — won't read trivial "ok" responses.
- **Queue for concurrent windows** — multiple Claude sessions don't overlap audio.

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
| `TTS_ENGINE` | `edge` | `edge`, `system`, `piper`, or `elevenlabs`. |
| `TTS_VOICE` | `zh-TW-HsiaoChenNeural` | Engine-specific voice ID. |
| `TTS_MODE` | `progress` | `llm`, `progress`, `first`, `summary`, or `full`. Switchable at runtime via `/listen <mode>`. |
| `TTS_LLM_MODEL` | `claude-haiku-4-5` | Model `claude -p` calls when `TTS_MODE=llm`. |
| `TTS_LLM_TIMEOUT_SEC` | `60` | Give up on the LLM rewrite after this many seconds and fall back to `progress`. |
| `TTS_MIN_WORDS` | `20` | Skip TTS if response shorter than this. |
| `TTS_MAX_CHARS` | `500` | Truncate longer responses. |
| `TTS_RATE` | `200` | Rough words-per-minute (engine-specific mapping). |
| `ANNOUNCE_PROJECT` | `1` | Prepend project / window name before spoken text. |
| `PIPER_VOICES_DIR` | `~/.cache/piper-voices` | Piper voice files location. |

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
  3. Strip code blocks and markdown noise
  4. Truncate to TTS_MAX_CHARS
  5. Acquire the per-host lock (queue if another window is speaking)
  6. Dispatch to TTS_ENGINE
        ↓
TTS engine plays audio in the background — never blocks Claude Code.
```

## Logs

`%TEMP%\listen-claude.log` (Windows) or `$TMPDIR/listen-claude.log` (Unix).

## Coexistence with other Claude Code plugins

Listen-Claude only adds a `Stop` hook. It plays nicely with any other plugin that uses `SessionStart` / `SessionEnd` / `PreToolUse` etc. — including [Kaikou-Claude](https://github.com/GeniusPudding/Kaikou-Claude) (Chinese voice input). The `patch_settings.py` script matches its own entries by a known substring so re-install / uninstall never touches unrelated hooks.
