#!/usr/bin/env bash
# Control Listen-Claude TTS: on/off + reading mode.
# Usage:
#   bash scripts/toggle.sh                  toggle current on/off state
#   bash scripts/toggle.sh on               force on
#   bash scripts/toggle.sh off              force off
#   bash scripts/toggle.sh status           print on/off state
#   bash scripts/toggle.sh llm              Claude-rewritten spoken summary (TTS_MODE=llm)
#   bash scripts/toggle.sh smart            alias for llm
#   bash scripts/toggle.sh brief            short reading (TTS_MODE=first)
#   bash scripts/toggle.sh progress         intro + bullets (TTS_MODE=progress)
#   bash scripts/toggle.sh summary          first sentence per paragraph
#   bash scripts/toggle.sh detailed         read everything (TTS_MODE=full)
#   bash scripts/toggle.sh mode             print current mode

set -u

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
marker="${TMPDIR:-/tmp}/listen-claude.disabled"
env_file="$repo_dir/.env"
action="${1:-toggle}"
param="${2:-}"
action="$(echo "$action" | tr '[:upper:]' '[:lower:]')"

# Aliases that map user-friendly words to TTS_MODE values.
case "$action" in
    brief|short)    action="first" ;;
    detailed|long)  action="full"  ;;
    smart)          action="llm"   ;;
    # Engine quick-switch aliases. `auto` = hybrid router (Chinese →
    # cloned voice via gptsovits, English-heavy → edge). `default`/
    # `xiaoxiao` snap back to the always-clear Edge voice.
    default|xiaoxiao)        action="edge" ;;
    cloned|hybrid)           action="auto" ;;
    ex|experimental|ig)      action="gptsovits" ;;
esac

set_mode() {
    local mode="$1"
    if [[ ! -f "$env_file" && -f "$repo_dir/.env.example" ]]; then
        cp "$repo_dir/.env.example" "$env_file"
    fi
    if [[ -f "$env_file" ]]; then
        local tmp; tmp="$(mktemp)"
        grep -v '^[[:space:]]*TTS_MODE[[:space:]]*=' "$env_file" > "$tmp" || true
        printf 'TTS_MODE=%s\n' "$mode" >> "$tmp"
        mv "$tmp" "$env_file"
    fi
    echo "Listen-Claude mode: $mode"
}

get_mode() {
    if [[ -f "$env_file" ]]; then
        local line
        line="$(grep -E '^[[:space:]]*TTS_MODE[[:space:]]*=' "$env_file" | tail -n1)"
        if [[ -n "$line" ]]; then
            echo "${line#*=}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
            return
        fi
    fi
    echo "progress (default)"
}

set_engine() {
    local engine="$1"
    if [[ ! -f "$env_file" && -f "$repo_dir/.env.example" ]]; then
        cp "$repo_dir/.env.example" "$env_file"
    fi
    if [[ -f "$env_file" ]]; then
        local tmp; tmp="$(mktemp)"
        grep -v '^[[:space:]]*TTS_ENGINE[[:space:]]*=' "$env_file" > "$tmp" || true
        printf 'TTS_ENGINE=%s\n' "$engine" >> "$tmp"
        mv "$tmp" "$env_file"
    fi
    echo "Listen-Claude engine: $engine"
}

get_engine() {
    if [[ -f "$env_file" ]]; then
        local line
        line="$(grep -E '^[[:space:]]*TTS_ENGINE[[:space:]]*=' "$env_file" | tail -n1)"
        if [[ -n "$line" ]]; then
            echo "${line#*=}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
            return
        fi
    fi
    echo "edge (default)"
}

case "$action" in
    first|progress|summary|full|llm)
        set_mode "$action"; exit 0
        ;;
    mode)
        echo "Listen-Claude mode: $(get_mode)"; exit 0
        ;;
    edge|system|piper|elevenlabs|fish|gptsovits|auto)
        set_engine "$action"; exit 0
        ;;
    engine)
        echo "Listen-Claude engine: $(get_engine)"; exit 0
        ;;
    notify)
        # Per-project notify silencer — see toggle.ps1 'notify' block
        # for rationale. Default to current dir basename.
        sub="${param:-status}"
        sub="$(echo "$sub" | tr '[:upper:]' '[:lower:]')"
        disabled_dir="${TMPDIR:-/tmp}/listen-claude-notify-disabled"
        proj="$(basename "$(pwd)")"
        safe="$(echo "$proj" | tr -c 'A-Za-z0-9_' '_')"
        flag="$disabled_dir/$safe.flag"
        case "$sub" in
            off)
                mkdir -p "$disabled_dir"; : > "$flag"
                echo "Listen-Claude notify: OFF for $proj"
                ;;
            on)
                rm -f "$flag"
                echo "Listen-Claude notify: ON for $proj"
                ;;
            toggle)
                if [[ -f "$flag" ]]; then
                    rm -f "$flag"; echo "Listen-Claude notify: ON for $proj"
                else
                    mkdir -p "$disabled_dir"; : > "$flag"
                    echo "Listen-Claude notify: OFF for $proj"
                fi
                ;;
            *)
                state=$([[ -f "$flag" ]] && echo OFF || echo ON)
                echo "Listen-Claude notify: $state for $proj"
                ;;
        esac
        exit 0
        ;;
    voice)
        if [[ -z "$param" ]]; then
            voices_dir="$repo_dir/voices"
            found=()
            if [[ -d "$voices_dir" ]]; then
                for d in "$voices_dir"/*/; do
                    [[ -f "$d/profile.json" ]] && found+=("$(basename "$d")")
                done
            fi
            if (( ${#found[@]} > 0 )); then
                echo "Listen-Claude voices: ${found[*]}"
            else
                echo "Listen-Claude voices: (none — run clone-voice to create one)"
            fi
            exit 0
        fi
        if [[ ! -f "$env_file" && -f "$repo_dir/.env.example" ]]; then
            cp "$repo_dir/.env.example" "$env_file"
        fi
        if [[ -f "$env_file" ]]; then
            tmp="$(mktemp)"
            grep -vE '^[[:space:]]*(TTS_ENGINE|GPTSOVITS_VOICE_PROFILE)[[:space:]]*=' \
                "$env_file" > "$tmp" || true
            printf 'TTS_ENGINE=gptsovits\nGPTSOVITS_VOICE_PROFILE=%s\n' "$param" >> "$tmp"
            mv "$tmp" "$env_file"
        fi
        echo "Listen-Claude voice: $param (engine=gptsovits)"
        exit 0
        ;;
esac

# Hard-stop: drops the disabled marker, purges unplayed queue items,
# and kills the worker process tree (so the audio subprocess stops
# mid-sentence). Without this, anything already queued keeps playing
# for up to a minute after toggle off — not what the user expects.
stop_listening() {
    local tmpdir="${TMPDIR:-/tmp}"
    rm -f "$tmpdir/listen-claude-queue"/*.json 2>/dev/null
    local lock="$tmpdir/listen-claude.lock"
    if [[ -f "$lock" ]]; then
        local worker_pid
        worker_pid="$(<"$lock")"
        worker_pid="${worker_pid//[!0-9]/}"
        if [[ -n "$worker_pid" ]]; then
            # Kill children first (the audio playback subprocess),
            # then the worker. pkill -P on macOS / Linux is safe even
            # if the pid doesn't exist or has no children.
            pkill -9 -P "$worker_pid" 2>/dev/null || true
            kill -9 "$worker_pid" 2>/dev/null || true
        fi
        rm -f "$lock"
    fi
}

# on/off/status/toggle.
exists=0
[[ -f "$marker" ]] && exists=1

case "$action" in
    on)
        [[ $exists -eq 1 ]] && rm -f "$marker"
        state="ON"
        ;;
    off)
        [[ $exists -eq 0 ]] && : > "$marker"
        stop_listening
        state="OFF"
        ;;
    status)
        state=$([[ $exists -eq 1 ]] && echo "OFF" || echo "ON")
        ;;
    toggle|*)
        if [[ $exists -eq 1 ]]; then
            rm -f "$marker"; state="ON"
        else
            : > "$marker"; stop_listening; state="OFF"
        fi
        ;;
esac

echo "Listen-Claude TTS: $state"
