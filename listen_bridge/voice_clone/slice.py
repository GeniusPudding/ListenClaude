"""Slice each source WAV by its transcript timestamps into training
segments + write the GPT-SoVITS ``list.txt`` aggregator file.

Expected transcript format (produced by transcribe.py and editable by
the user):

    [  0.7s -   2.6s]  浩子家今天要來跟大家介紹
    [  2.6s -   4.9s]  ...

list.txt format (GPT-SoVITS convention):

    <abs_path_to_segment.wav>|<speaker_name>|<lang>|<text>
"""

from __future__ import annotations

import os
import re
import subprocess
from . import profile as profile_mod


_RE = re.compile(r"\[\s*([\d.]+)s\s*-\s*([\d.]+)s\s*\]\s+(.+?)\s*$")


def run(name: str, *, lang: str = "zh",
        min_sec: float = 0.8, max_sec: float = 12.0,
        pad: float = 0.1) -> int:
    """Cut every transcribed source into per-segment WAVs at 32 kHz mono
    (GPT-SoVITS training format) and refresh voices/<name>/list.txt.

    Returns the total segment count. Idempotent: regenerates from
    scratch each time (segments dir is wiped then re-cut so edits to
    the transcripts always take effect).
    """
    prof = profile_mod.load(name)
    src_dir = os.path.join(prof.home, "source")
    seg_dir = os.path.join(prof.home, "segments")
    list_path = os.path.join(prof.home, "list.txt")

    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f"no source/ under {prof.home}")

    # Wipe + re-cut so editing a transcript doesn't leave stale segments
    if os.path.isdir(seg_dir):
        for f in os.listdir(seg_dir):
            try: os.unlink(os.path.join(seg_dir, f))
            except OSError: pass
    os.makedirs(seg_dir, exist_ok=True)

    count = 0
    with open(list_path, "w", encoding="utf-8") as fl:
        for wav_name in sorted(os.listdir(src_dir)):
            if not wav_name.endswith(".wav"):
                continue
            tr = os.path.join(src_dir, wav_name[:-4] + ".transcript.txt")
            if not os.path.isfile(tr):
                print(f"  [slice] no transcript for {wav_name}, skipping")
                continue
            wav_abs = os.path.join(src_dir, wav_name)
            tag = os.path.splitext(wav_name)[0]
            print(f"  [slice] {wav_name}")
            with open(tr, encoding="utf-8") as f:
                for line in f:
                    m = _RE.match(line.rstrip())
                    if not m:
                        continue
                    start, end, text = float(m.group(1)), float(m.group(2)), m.group(3).strip()
                    dur = end - start
                    if not text or dur < min_sec or dur > max_sec:
                        continue
                    seg_name = f"{tag}-{count:03d}.wav"
                    seg_path = os.path.join(seg_dir, seg_name)
                    subprocess.run(
                        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                         "-ss", f"{max(0, start - pad)}",
                         "-to", f"{end + pad}",
                         "-i", wav_abs,
                         "-ac", "1", "-ar", "32000",  # GPT-SoVITS expects 32 kHz mono
                         seg_path],
                        check=True,
                    )
                    fl.write(f"{seg_path}|{name}|{lang}|{text}\n")
                    count += 1
    print(f"  [slice] {count} segments → {seg_dir}")
    print(f"  [slice] list at {list_path}")

    # Pin the slice config in profile.json so re-runs are explainable
    prof.raw.setdefault("slicing", {}).update({
        "lang": lang, "min_sec": min_sec, "max_sec": max_sec,
        "pad_sec": pad, "segment_count": count,
    })
    prof.save()
    return count
