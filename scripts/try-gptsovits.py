"""Iterative CLI for tuning GPT-SoVITS playback.

Usage:
    .venv/Scripts/python.exe scripts/try-gptsovits.py
    .venv/Scripts/python.exe scripts/try-gptsovits.py --text "hello, 中英混 test"
    .venv/Scripts/python.exe scripts/try-gptsovits.py --speed 0.8 --temp 0.5
    .venv/Scripts/python.exe scripts/try-gptsovits.py --ref voices/ig-demo/reference-c.wav

Sends a synthesis request to a running GPT-SoVITS api_v2 server
(listen_bridge.config.GPTSOVITS_HOST:PORT) and plays the result.
Saves the WAV next to the script so you can re-listen / share.

No fallback to Edge — this tool is for direct A/B testing of the
GPT-SoVITS server with tweaked params. Failures print the API error
so you can see exactly what the server objected to.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Make sure listen_bridge is importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from listen_bridge import config  # noqa: E402


DEFAULT_TEXT = (
    "已經訓練好 GPT-SoVITS,這是新的克隆聲音念中英混的測試。"
    "API、debug、commit 應該都念得順。"
)

# Default reference — falls back to voices/ig-demo/reference-c.wav
# (7.9 s, the short clip GPT-SoVITS accepts).
DEFAULT_REF = REPO / "voices/ig-demo/reference-c.wav"
DEFAULT_REF_TEXT = REPO / "voices/ig-demo/reference-c.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--text", "-t", default=DEFAULT_TEXT, help="text to synthesise")
    p.add_argument("--ref", default=str(DEFAULT_REF),
                   help="reference WAV/MP3 (3-10 s, single speaker, clean)")
    p.add_argument("--ref-text",
                   help="transcript of --ref (loaded from <ref-stem>.txt if omitted)")
    p.add_argument("--lang", default="zh", help="text language (zh / en / ja / ko / ...)")

    # Sampling
    p.add_argument("--top-k", type=int, default=config.GPTSOVITS_TOP_K)
    p.add_argument("--top-p", type=float, default=config.GPTSOVITS_TOP_P)
    p.add_argument("--temp", type=float, default=config.GPTSOVITS_TEMPERATURE,
                   help="sampling temperature; lower = more deterministic")
    p.add_argument("--rep-penalty", type=float, default=config.GPTSOVITS_REPETITION_PENALTY)

    # Pacing
    p.add_argument("--speed", type=float, default=config.GPTSOVITS_SPEED_FACTOR,
                   help="speed factor; 1.0 = ref pace, <1 = slower, >1 = faster")
    p.add_argument("--split", default=config.GPTSOVITS_TEXT_SPLIT,
                   choices=["cut0", "cut1", "cut2", "cut3", "cut4", "cut5"],
                   help="cut0 = whole text; cut5 = every punctuation mark")
    p.add_argument("--fragment-interval", type=float, default=config.GPTSOVITS_FRAGMENT_INTERVAL,
                   help="pause (s) between fragments when split != cut0")

    # Output
    p.add_argument("--out", default=None,
                   help="write WAV to this path (default: voices/_test-NNN.wav)")
    p.add_argument("--no-play", action="store_true", help="don't auto-play the result")
    p.add_argument("--server", default=f"http://{config.GPTSOVITS_HOST}:{config.GPTSOVITS_PORT}")
    return p.parse_args()


def resolve_ref_text(ref_path: str, override: str | None) -> str:
    if override:
        return override
    txt_path = Path(ref_path).with_suffix(".txt")
    if txt_path.is_file():
        return txt_path.read_text(encoding="utf-8").strip()
    return ""


def next_out_path() -> Path:
    voices = REPO / "voices"
    voices.mkdir(exist_ok=True)
    for i in range(1, 1000):
        p = voices / f"_test-{i:03d}.wav"
        if not p.exists():
            return p
    return voices / "_test-overflow.wav"


def play_wav(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
            check=False,
        )
    elif sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)
    else:
        for cmd in (["aplay", "-q", str(path)], ["paplay", str(path)]):
            try:
                subprocess.run(cmd, check=False)
                return
            except FileNotFoundError:
                continue


def main() -> int:
    args = parse_args()

    if not Path(args.ref).is_file():
        print(f"ERR: reference audio not found: {args.ref}", file=sys.stderr)
        return 2
    ref_text = resolve_ref_text(args.ref, args.ref_text)

    body = {
        "text": args.text,
        "text_lang": args.lang,
        "ref_audio_path": str(Path(args.ref).resolve()),
        "prompt_text": ref_text,
        "prompt_lang": args.lang,
        "top_k": args.top_k,
        "top_p": args.top_p,
        "temperature": args.temp,
        "repetition_penalty": args.rep_penalty,
        "text_split_method": args.split,
        "batch_size": 1,
        "speed_factor": args.speed,
        "fragment_interval": args.fragment_interval,
        "media_type": "wav",
        "streaming_mode": False,
    }

    print("=" * 60)
    print(f"Server:  {args.server}")
    print(f"Ref:     {args.ref}")
    print(f"Ref text:{ref_text[:60]}{'...' if len(ref_text) > 60 else ''}")
    print(f"Text:    {args.text[:80]}{'...' if len(args.text) > 80 else ''}")
    print(f"Params:  speed={args.speed} temp={args.temp} top_p={args.top_p} "
          f"top_k={args.top_k} rep={args.rep_penalty} split={args.split}")
    print("=" * 60)

    req = urllib.request.Request(
        args.server + "/tts",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=config.GPTSOVITS_SYNTH_TIMEOUT_SEC) as r:
            audio = r.read()
            print(f"synth: HTTP {r.status}, {len(audio):,} B in {time.time()-t0:.1f}s")
    except urllib.error.HTTPError as e:
        msg = e.read()[:500].decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {msg}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERR: {e}", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else next_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    print(f"saved:   {out_path}")

    if not args.no_play:
        play_wav(out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
