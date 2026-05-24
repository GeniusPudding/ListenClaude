"""Voice cloning pipeline for Listen-Claude.

A voice profile is a directory under ``voices/<name>/`` containing:

    profile.json      ← engine config (refs, trained ckpt, synthesis params)
    source/           ← raw audio downloads + their Whisper transcripts
    segments/         ← cut training segments
    training/         ← GPT-SoVITS s1 artifacts (BERT/HuBERT/semantic +
                        fine-tuned GPT_weights)
    reference.wav     ← 3-10 s clip used at inference time
    reference.txt     ← transcript of the reference clip
    tts_infer.yaml    ← api_v2 config pointing at the trained GPT and
                        the shared base v2 SoVITS decoder

The CLI (``scripts/clone-voice.py``) drives the pipeline through six
idempotent stages: acquire, transcribe, slice, train, select-ref,
activate. Profiles can be partially built and resumed.
"""
