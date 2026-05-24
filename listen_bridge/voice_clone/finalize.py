"""Choose a reference clip + write tts_infer.yaml + activate the profile.

GPT-SoVITS's api_v2 needs a 3-10 s reference WAV per request to clone
the speaker's timbre on top of the fine-tuned GPT's prosody. This
module cuts that clip from one of the source files and writes the
api_v2 config that points at all the pieces.
"""

from __future__ import annotations

import os
import subprocess
from typing import Iterable

from . import profile as profile_mod
from .. import config


_PRETRAINED = os.path.join(
    config.GPTSOVITS_SOURCE_DIR, "GPT_SoVITS", "pretrained_models"
)
_BERT_BASE = os.path.join(_PRETRAINED, "chinese-roberta-wwm-ext-large")
_HUBERT_BASE = os.path.join(_PRETRAINED, "chinese-hubert-base")
_BASE_SOVITS = os.path.join(
    _PRETRAINED, "gsv-v2final-pretrained", "s2G2333k.pth"
)


def cut_reference(name: str, source_wav: str, *,
                  start: float, end: float,
                  text: str) -> tuple[str, str]:
    """Cut a 3-10 s reference clip from `source_wav` (within voices/<name>/source/
    or absolute path) and save it as voices/<name>/reference.wav with a
    matching .txt transcript. Returns (wav, txt) absolute paths."""
    prof = profile_mod.load(name)
    dur = end - start
    if dur < 3 or dur > 10:
        raise ValueError(f"reference must be 3-10 s; got {dur:.1f}s")

    if not os.path.isabs(source_wav):
        source_wav = os.path.join(prof.home, "source", source_wav)
    if not os.path.isfile(source_wav):
        raise FileNotFoundError(source_wav)

    ref_wav = os.path.join(prof.home, "reference.wav")
    ref_txt = os.path.join(prof.home, "reference.txt")

    print(f"  [finalize] cut {start:.1f}-{end:.1f}s from {os.path.basename(source_wav)}")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", str(start), "-to", str(end),
         "-i", source_wav, "-ac", "1", "-ar", "44100", ref_wav],
        check=True,
    )
    with open(ref_txt, "w", encoding="utf-8") as f:
        f.write(text.strip())

    prof.update_engine("gptsovits", {
        "reference":      os.path.relpath(ref_wav, prof.home),
        "reference_text": os.path.relpath(ref_txt, prof.home),
        # Pin sensible synthesis defaults if the profile doesn't have any.
        **({"synthesis": _DEFAULT_SYNTH}
            if "synthesis" not in prof.engine("gptsovits") else {}),
    })
    prof.save()
    return ref_wav, ref_txt


_DEFAULT_SYNTH = {
    "speed_factor": 0.7,
    "temperature": 0.5,
    "top_p": 0.5,
    "top_k": 15,
    "repetition_penalty": 1.35,
    "text_split_method": "cut0",
    "fragment_interval": 0.3,
}


def write_tts_infer_yaml(name: str) -> str:
    """Write voices/<name>/tts_infer.yaml — the file api_v2 reads at
    server start. Path is also pinned into profile.json."""
    prof = profile_mod.load(name)
    gptsovits_cfg = prof.engine("gptsovits")
    if not gptsovits_cfg.get("gpt_ckpt"):
        raise RuntimeError(
            f"profile {name} has no trained gpt_ckpt — run `train` first"
        )

    yaml_path = os.path.join(prof.home, "tts_infer.yaml")
    gpt_ckpt = prof.resolve(gptsovits_cfg["gpt_ckpt"])
    body = (
        "custom:\n"
        "  device: cuda\n"
        "  is_half: true\n"
        "  version: v2\n"
        f"  t2s_weights_path: {gpt_ckpt}\n"
        f"  vits_weights_path: {_BASE_SOVITS}\n"
        f"  bert_base_path: {_BERT_BASE}\n"
        f"  cnhuhbert_base_path: {_HUBERT_BASE}\n"
    )
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  [finalize] wrote {yaml_path}")

    prof.update_engine("gptsovits", {
        "tts_infer_yaml": os.path.relpath(yaml_path, prof.home),
    })
    prof.save()
    return yaml_path


def activate(name: str) -> None:
    """Pin this voice as the active GPT-SoVITS profile by writing
    TTS_ENGINE=gptsovits and GPTSOVITS_VOICE_PROFILE=<name> into .env.
    Falls back gracefully if .env doesn't exist yet."""
    env_path = os.path.join(config._REPO_ROOT, ".env")
    if os.path.isfile(env_path):
        lines = [
            ln for ln in open(env_path, encoding="utf-8").read().splitlines()
            if not (ln.lstrip().startswith("TTS_ENGINE=")
                    or ln.lstrip().startswith("GPTSOVITS_VOICE_PROFILE="))
        ]
    else:
        lines = []
    lines.append("TTS_ENGINE=gptsovits")
    lines.append(f"GPTSOVITS_VOICE_PROFILE={name}")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  [finalize] activated profile '{name}' in .env")
