"""CLI entry point for the voice-clone pipeline.

Run via ``scripts/clone-voice.{py,ps1,sh} <subcommand> [args]``.

Subcommands::

    acquire <name> <url-or-file> [--start S --duration N]
    transcribe <name> [--force] [--model MODEL]
    slice <name> [--lang zh] [--min 0.8] [--max 12.0]
    train <name> [--epochs 15] [--batch 4]
    ref <name> <source-wav> --start S --end E --text "<transcript>"
    activate <name>
    use <name>                # alias for activate
    list
    info <name>
    pipeline <name> <url-or-file>   # acquire + transcribe (and stop)

The pipeline is designed to be **resumable**: each step writes its
artifacts then updates voices/<name>/profile.json, so re-running a step
picks up where the previous one left off (or no-ops if up to date).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import acquire, transcribe, slice as slicer, train, finalize, profile as profile_mod


def _common_name(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="voice profile name (becomes voices/<name>/)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clone-voice",
        description="Listen-Claude voice cloning pipeline",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("acquire", help="download / import an audio source")
    _common_name(pa)
    pa.add_argument("source", help="URL (yt-dlp) or path to a local audio file")
    pa.add_argument("--start", type=float, help="trim seconds from start")
    pa.add_argument("--duration", type=float, help="keep only N seconds")

    pt = sub.add_parser("transcribe", help="auto-transcribe all sources (Whisper)")
    _common_name(pt)
    pt.add_argument("--force", action="store_true", help="redo existing transcripts")
    pt.add_argument("--model", default=None, help="faster-whisper model (default: medium)")

    ps = sub.add_parser("slice", help="cut training segments from transcripts")
    _common_name(ps)
    ps.add_argument("--lang", default="zh")
    ps.add_argument("--min", type=float, default=0.8, help="min segment length (s)")
    ps.add_argument("--max", type=float, default=12.0, help="max segment length (s)")

    ptr = sub.add_parser("train", help="fine-tune GPT-SoVITS s1 on the segments")
    _common_name(ptr)
    ptr.add_argument("--epochs", type=int, default=15)
    ptr.add_argument("--batch", type=int, default=4)

    pr = sub.add_parser("ref", help="cut the 3-10 s reference clip")
    _common_name(pr)
    pr.add_argument("source", help="source WAV filename (under voices/<name>/source/)"
                                   " or absolute path")
    pr.add_argument("--start", type=float, required=True)
    pr.add_argument("--end", type=float, required=True)
    pr.add_argument("--text", required=True, help="transcript of the reference clip")

    pact = sub.add_parser("activate", help="write profile into .env, restart server next call")
    _common_name(pact)

    puse = sub.add_parser("use", help="alias for activate")
    _common_name(puse)

    sub.add_parser("list", help="list all profiles under voices/")

    pi = sub.add_parser("info", help="dump profile.json for <name>")
    _common_name(pi)

    ppl = sub.add_parser("pipeline",
                         help="convenience: acquire + transcribe, then stop "
                              "so you can review / edit transcripts before slice")
    _common_name(ppl)
    ppl.add_argument("source", help="URL or local audio file")
    ppl.add_argument("--start", type=float)
    ppl.add_argument("--duration", type=float)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "acquire":
        if args.source.startswith(("http://", "https://")):
            acquire.from_url(args.name, args.source,
                             start=args.start, duration=args.duration)
        else:
            acquire.from_file(args.name, args.source)
        return 0

    if args.cmd == "transcribe":
        transcribe.all_sources(args.name, model=args.model, force=args.force)
        return 0

    if args.cmd == "slice":
        n = slicer.run(args.name, lang=args.lang, min_sec=args.min, max_sec=args.max)
        if n == 0:
            print("  (no segments produced — did you transcribe + edit yet?)")
            return 1
        return 0

    if args.cmd == "train":
        train.run(args.name, epochs=args.epochs, batch_size=args.batch)
        finalize.write_tts_infer_yaml(args.name)
        return 0

    if args.cmd == "ref":
        finalize.cut_reference(args.name, args.source,
                               start=args.start, end=args.end, text=args.text)
        # Also refresh the yaml in case the trained ckpt path changed
        if profile_mod.load(args.name).engine("gptsovits").get("gpt_ckpt"):
            finalize.write_tts_infer_yaml(args.name)
        return 0

    if args.cmd in ("activate", "use"):
        finalize.activate(args.name)
        return 0

    if args.cmd == "list":
        for prof in profile_mod.list_profiles():
            desc = prof.description and f" — {prof.description}"
            engs = ", ".join(sorted(prof.raw.get("engines", {}))) or "(none)"
            print(f"  {prof.name}{desc}   engines: {engs}")
        return 0

    if args.cmd == "info":
        prof = profile_mod.load(args.name)
        print(json.dumps(prof.raw, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "pipeline":
        if args.source.startswith(("http://", "https://")):
            acquire.from_url(args.name, args.source,
                             start=args.start, duration=args.duration)
        else:
            acquire.from_file(args.name, args.source)
        transcribe.all_sources(args.name)
        print("\nReview / edit voices/{0}/source/*.transcript.txt then run:".format(args.name))
        print(f"  clone-voice slice {args.name}")
        print(f"  clone-voice train {args.name}")
        print(f"  clone-voice ref {args.name} <source.wav> --start S --end E --text '...'")
        print(f"  clone-voice activate {args.name}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
