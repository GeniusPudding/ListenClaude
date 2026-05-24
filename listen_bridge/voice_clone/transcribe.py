"""Transcribe each source WAV into a Whisper-style segmented txt file
the user can hand-edit before slicing.

Output format (one segment per line):

    [  0.7s -   2.6s]  浩子家今天要來跟大家介紹

The pipeline expects ``faster-whisper`` to live in ``.venv-gptsovits``
because that's where the GPT-SoVITS install already pulled it in. To
keep dependencies tight in the main venv we run transcription as a
subprocess in the other venv instead of importing it directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from . import profile as profile_mod
from .. import config


_GPTSOVITS_PY = config.GPTSOVITS_PYTHON
_FW_MODEL = os.getenv("WHISPER_MODEL", "medium")


_DRIVER = r"""
import json, sys
from faster_whisper import WhisperModel

audio_path = sys.argv[1]
out_path = sys.argv[2]
model_name = sys.argv[3] if len(sys.argv) > 3 else "medium"

model = WhisperModel(model_name, device="cuda", compute_type="float16")
segments, info = model.transcribe(
    audio_path, language=None, word_timestamps=False, vad_filter=True,
)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"# Detected language: {info.language}  (prob {info.language_probability:.2f})\n\n")
    for s in segments:
        f.write(f"[{s.start:5.1f}s - {s.end:5.1f}s]  {s.text.strip()}\n")
print(f"transcribed -> {out_path}")
"""


def all_sources(name: str, *, model: str | None = None,
                force: bool = False) -> list[str]:
    """Transcribe every WAV under voices/<name>/source/ that doesn't
    already have a matching .transcript.txt. Returns the list of
    transcript paths produced (or skipped).

    Pass ``force=True`` to re-run transcription even if a transcript
    file is already present (overwrites the existing one).
    """
    prof = profile_mod.load(name)
    src_dir = os.path.join(prof.home, "source")
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f"no source/ under {prof.home} — run `acquire` first")

    if not os.path.isfile(_GPTSOVITS_PY):
        raise FileNotFoundError(
            f"GPT-SoVITS venv python not found at {_GPTSOVITS_PY}. "
            "Whisper transcription needs `.venv-gptsovits` set up "
            "(scripts/install-gpt-sovits.{ps1,sh})."
        )

    model_name = model or _FW_MODEL
    outputs: list[str] = []
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".wav"):
            continue
        wav = os.path.join(src_dir, fn)
        tr = os.path.join(src_dir, fn[:-4] + ".transcript.txt")
        if os.path.isfile(tr) and not force:
            print(f"  [transcribe] skip {os.path.basename(tr)} (exists)")
            outputs.append(tr)
            continue
        print(f"  [transcribe] {os.path.basename(wav)} → {os.path.basename(tr)}")
        subprocess.run(
            [_GPTSOVITS_PY, "-c", _DRIVER, wav, tr, model_name],
            check=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        outputs.append(tr)
    return outputs
