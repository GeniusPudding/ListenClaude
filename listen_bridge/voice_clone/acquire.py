"""Acquire raw voice audio from a URL or local file.

yt-dlp handles the URL → audio step for hundreds of sites (YouTube,
Instagram reels, TikTok, X, Bilibili, podcasts...). Local files (.wav
.mp3 .m4a etc.) are accepted directly.

Output goes to ``voices/<name>/source/<slug>.wav`` (44.1 kHz mono)
and the profile.json's ``sources`` list is updated.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from urllib.parse import urlparse

from . import profile as profile_mod


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-")
    return s[:64] or "source"


def _resolve_yt_dlp() -> str:
    """Locate yt-dlp inside the main Listen-Claude venv (where we install
    it) or on PATH."""
    candidates = [
        os.path.join(profile_mod.config._REPO_ROOT, ".venv", "Scripts", "yt-dlp.exe"),
        os.path.join(profile_mod.config._REPO_ROOT, ".venv", "bin", "yt-dlp"),
        shutil.which("yt-dlp"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "yt-dlp not found. Install with: .venv/Scripts/python.exe -m pip install yt-dlp"
    )


def from_url(name: str, url: str, *, start: float | None = None,
             duration: float | None = None) -> str:
    """Download audio from `url` into voices/<name>/source/.
    Returns the absolute path of the produced WAV.

    `start` / `duration` (seconds) trim the resulting WAV via ffmpeg.
    Idempotent: skips download if the target WAV already exists.
    """
    prof = profile_mod.load(name, create_if_missing=True)
    src_dir = os.path.join(prof.home, "source")
    os.makedirs(src_dir, exist_ok=True)

    parsed = urlparse(url)
    # Use the last path component (e.g. instagram reel id) as the slug.
    slug = _slug(parsed.path.rstrip("/").split("/")[-1] or parsed.netloc)
    raw_template = os.path.join(src_dir, f"{slug}.%(ext)s")
    final_wav = os.path.join(src_dir, f"{slug}.wav")

    if os.path.isfile(final_wav):
        print(f"  [acquire] skip {final_wav} (already present)")
    else:
        yt_dlp = _resolve_yt_dlp()
        # `bestaudio` gives whatever audio-only stream the site exposes.
        print(f"  [acquire] yt-dlp {url}")
        subprocess.run(
            [yt_dlp, "-f", "bestaudio", "-o", raw_template, "--no-warnings", url],
            check=True,
        )
        # The download may land as .m4a / .webm / .mp3 — convert to WAV.
        downloaded = None
        for ext in ("m4a", "mp3", "webm", "opus", "ogg", "aac", "wav"):
            cand = os.path.join(src_dir, f"{slug}.{ext}")
            if os.path.isfile(cand):
                downloaded = cand
                break
        if not downloaded:
            raise RuntimeError(f"yt-dlp left no recognised audio file in {src_dir}")
        if downloaded != final_wav:
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            if start is not None:
                cmd += ["-ss", str(start)]
            if duration is not None:
                cmd += ["-t", str(duration)]
            cmd += ["-i", downloaded, "-ac", "1", "-ar", "44100", final_wav]
            subprocess.run(cmd, check=True)
            if downloaded != final_wav:
                try: os.unlink(downloaded)
                except OSError: pass
        print(f"  [acquire] saved {final_wav}")

    prof.add_source(url, os.path.relpath(final_wav, prof.home))
    prof.save()
    return final_wav


def from_file(name: str, src_path: str) -> str:
    """Copy a local audio file into voices/<name>/source/ as WAV.
    Returns absolute path of the produced WAV."""
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)
    prof = profile_mod.load(name, create_if_missing=True)
    src_dir = os.path.join(prof.home, "source")
    os.makedirs(src_dir, exist_ok=True)

    slug = _slug(os.path.splitext(os.path.basename(src_path))[0])
    final_wav = os.path.join(src_dir, f"{slug}.wav")
    if os.path.isfile(final_wav):
        print(f"  [acquire] skip {final_wav}")
    else:
        print(f"  [acquire] convert {src_path} → {final_wav}")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", src_path, "-ac", "1", "-ar", "44100", final_wav],
            check=True,
        )

    prof.add_source(f"file://{os.path.abspath(src_path)}",
                    os.path.relpath(final_wav, prof.home))
    prof.save()
    return final_wav
