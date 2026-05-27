#!/usr/bin/env bash
# Play a batch of .wav files back-to-back via the user's own audio
# session. Use this from a real terminal when you need to listen to
# diagnostic renders that Listen-Claude generated under voices/_test/.
#
# Usage:
#   bash scripts/play-wavs.sh                          # all voices/_test/*.wav
#   bash scripts/play-wavs.sh -p 'diag-*.wav'          # filter glob
#   bash scripts/play-wavs.sh -d voices/_test          # different dir
#   bash scripts/play-wavs.sh -g 1.5                   # 1.5 s gap between clips

set -u

dir="voices/_test"
pattern="*.wav"
gap="0.8"

while (( $# > 0 )); do
    case "$1" in
        -d|--dir)     dir="$2"; shift 2;;
        -p|--pattern) pattern="$2"; shift 2;;
        -g|--gap)     gap="$2"; shift 2;;
        -h|--help)
            sed -n '2,12p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

# Resolve relative dir against repo root, not pwd.
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
case "$dir" in
    /*) abs_dir="$dir" ;;
    *)  abs_dir="$repo_dir/$dir" ;;
esac

if [[ ! -d "$abs_dir" ]]; then
    echo "no such directory: $abs_dir" >&2
    exit 1
fi

# Pick a player. afplay = macOS, aplay / paplay = Linux.
player=""
for cand in afplay aplay paplay; do
    if command -v "$cand" >/dev/null 2>&1; then player="$cand"; break; fi
done
if [[ -z "$player" ]]; then
    echo "no audio player on PATH (need afplay / aplay / paplay)" >&2
    exit 1
fi

shopt -s nullglob
files=( "$abs_dir"/$pattern )
shopt -u nullglob
if (( ${#files[@]} == 0 )); then
    echo "no files matching '$pattern' under $abs_dir"
    exit 0
fi

echo "playing ${#files[@]} file(s) from $abs_dir (player=$player)"
echo "------------------------------------------------------------"
for f in "${files[@]}"; do
    echo "  >>> $(basename "$f")"
    if [[ "$player" == "afplay" ]]; then
        afplay "$f"
    else
        "$player" -q "$f" >/dev/null 2>&1 || "$player" "$f" >/dev/null 2>&1
    fi
    if [[ -n "$gap" && "$gap" != "0" ]]; then
        sleep "$gap"
    fi
done
echo "done"
