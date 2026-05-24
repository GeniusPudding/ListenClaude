#!/usr/bin/env bash
# Listen-Claude voice cloning pipeline wrapper.
# Forwards everything to scripts/clone-voice.py under the main venv.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_py="$repo_dir/.venv/bin/python"
if [[ ! -x "$venv_py" ]]; then
    venv_py="$repo_dir/.venv/Scripts/python.exe"
fi
script="$repo_dir/scripts/clone-voice.py"

if [[ ! -x "$venv_py" && ! -f "$venv_py" ]]; then
    echo "Main venv not found — run install.sh first" >&2
    exit 1
fi

exec "$venv_py" "$script" "$@"
