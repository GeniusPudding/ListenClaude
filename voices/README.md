# Voice profiles

A **voice profile** is a self-contained directory under `voices/<name>/`
that bundles everything one cloned voice needs to run inside
Listen-Claude:

```
voices/<name>/
    profile.json        ← engine config (refs, trained ckpt, synthesis params)
    source/             ← raw audio downloads + their Whisper transcripts
    segments/           ← per-utterance training segments + list.txt
    training/           ← GPT-SoVITS fine-tune artifacts
                            ├── GPT_weights/<name>-eN.ckpt
                            └── logs_s1/, etc.
    reference.wav       ← the 3-10 s clip used at inference for voice
    reference.txt       ←   conditioning + its transcript
    tts_infer.yaml      ← api_v2 config pointing at the trained GPT and
                          the shared base v2 SoVITS decoder
```

All paths *inside* `profile.json` are relative to the profile's home
directory — profiles are movable / shareable as a single folder.

The whole `voices/` directory is gitignored. Cloned voices stay
private to your machine unless you explicitly publish a profile.

## Building a new voice

The `clone-voice` CLI walks you through the pipeline one step at a
time, and each step is idempotent so you can stop, inspect, and resume.

```bash
# 1. Acquire one or more source recordings (URL or local file).
.\scripts\clone-voice.ps1 acquire my-voice https://www.youtube.com/watch?v=…
.\scripts\clone-voice.ps1 acquire my-voice C:\path\to\recording.wav

# 2. Auto-transcribe each source (faster-whisper, runs on GPU).
.\scripts\clone-voice.ps1 transcribe my-voice
# → produces voices/my-voice/source/*.transcript.txt — open them in
#   your editor, fix Whisper's mistakes, save.

# 3. Slice transcripts into 3-12 s training segments.
.\scripts\clone-voice.ps1 slice my-voice

# 4. Fine-tune the GPT-SoVITS s1 model on the segments
#    (~10 min on an 8 GB GPU for 15 epochs / 50 segments).
.\scripts\clone-voice.ps1 train my-voice --epochs 15

# 5. Pick a 3-10 s reference clip from one of the sources.
.\scripts\clone-voice.ps1 ref my-voice ig-DCwkaM6SQfs.wav `
    --start 1.0 --end 8.5 --text "嗨大家好,我這邊跑出去..."

# 6. Activate — writes TTS_ENGINE=gptsovits + GPTSOVITS_VOICE_PROFILE=my-voice
#    into .env. Next Stop hook uses the new voice.
.\scripts\clone-voice.ps1 activate my-voice
```

Convenience shortcut (does steps 1 + 2 only, so you can review the
transcripts before slicing):

```bash
.\scripts\clone-voice.ps1 pipeline my-voice https://…
```

## Switching between voices

```bash
/listen voice              # list all profiles
/listen voice ig-demo      # switch to ig-demo
/listen voice my-voice     # switch to my-voice
/listen edge               # back to default Xiaoxiao (no clone)
/listen engine             # report current engine
```

Equivalent shell:

```bash
.\scripts\toggle.ps1 voice my-voice
.\scripts\toggle.ps1 edge
```

## Inspecting / debugging

```bash
.\scripts\clone-voice.ps1 list        # all profiles
.\scripts\clone-voice.ps1 info <name> # dump that profile's JSON

# Iterate on synthesis params without restarting:
.\venv\Scripts\python.exe scripts\try-gptsovits.py `
    --ref voices\my-voice\reference.wav --text "test text" `
    --speed 0.7 --temp 0.5 --no-play `
    --out voices\_test\my-voice-A.wav
```

## Notes & limits

- **Reference must be 3-10 seconds.** api_v2 rejects shorter / longer
  clips with HTTP 400.
- **Fine-tuned models inherit the speaker's language.** If you train
  on Chinese-only audio, the resulting GPT will silently elide English
  words at inference time. Mix Chinese + English in your training
  segments to keep code-switching working.
- **s2 (SoVITS) fine-tune is skipped on purpose.** On small datasets
  (<200 segments) it overfits and degrades audio quality. The base
  v2 SoVITS combined with your reference clip handles voice timbre.
- **Required deps.** Pipeline assumes `.venv` has yt-dlp + ffmpeg on
  PATH, and `.venv-gptsovits` is set up (see
  `scripts/install-fish-speech.{ps1,sh}` for the latter; GPT-SoVITS
  shares the venv).
