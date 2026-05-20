#!/usr/bin/env bash
# Install fish-speech into Listen-Claude's venv: PyTorch (CUDA if
# available, else CPU), the fish_speech package, and the 1.5 checkpoints.
# Safe to re-run (idempotent — re-downloads only if files are missing).
#
# Failure modes are loud but non-fatal: install.sh has already set up
# Listen-Claude with the default Edge engine, so even if this script
# fails halfway, TTS still works — you just don't get the GPU voice.

set -uo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="$repo_dir/.venv"
venv_py="$venv_dir/bin/python"
model_dir="${FISH_MODEL_DIR:-$HOME/.cache/fish-speech}"

echo
echo "=== install-fish-speech ==="
echo "Repo:       $repo_dir"
echo "venv:       $venv_dir"
echo "Model dir:  $model_dir"

if [[ ! -x "$venv_py" ]]; then
    echo "✗ venv not found. Run ./install.sh first." >&2
    exit 1
fi

# --- 1. Detect CUDA -----------------------------------------------------
cuda_tag="cpu"
cuda_version=""
if command -v nvidia-smi >/dev/null 2>&1; then
    if smi_out=$(nvidia-smi 2>&1); then
        if [[ "$smi_out" =~ CUDA[[:space:]]Version:[[:space:]]([0-9]+)\.([0-9]+) ]]; then
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            cuda_version="$major.$minor"
            # NVIDIA drivers are forward-compatible with older CUDA
            # toolkits, so we always pick the newest PyTorch wheel tag the
            # driver can run. Mapping based on what download.pytorch.org
            # actually ships.
            if   (( major >= 13 ));                then cuda_tag="cu128"
            elif (( major >= 12 && minor >= 8 ));  then cuda_tag="cu128"
            elif (( major >= 12 && minor >= 4 ));  then cuda_tag="cu124"
            elif (( major >= 12 ));                then cuda_tag="cu121"
            elif (( major == 11 && minor >= 8 ));  then cuda_tag="cu118"
            else                                        cuda_tag="cu121"; fi
        fi
    fi
fi

if [[ "$cuda_tag" == "cpu" ]]; then
    echo "! No NVIDIA GPU / CUDA detected — installing CPU-only PyTorch."
    echo "  fish-speech on CPU is 10-20x slower; Listen-Claude will"
    echo "  still work because TTS_ENGINE=fish auto-falls back to"
    echo "  TTS_FALLBACK_ENGINE (default: edge) when CUDA is missing."
else
    echo "✓ CUDA $cuda_version detected — installing PyTorch wheel tag '$cuda_tag'."
fi

# --- 2. Install PyTorch (skip if already present) -----------------------
if "$venv_py" -c "import torch" 2>/dev/null; then
    echo "✓ torch already installed in venv."
else
    echo "Installing torch / torchaudio (tag: $cuda_tag)..."
    if ! "$venv_py" -m pip install --upgrade \
            torch torchaudio \
            --index-url "https://download.pytorch.org/whl/$cuda_tag"; then
        echo "✗ torch install failed. fish-speech will not work; Listen-Claude will use the fallback engine." >&2
        exit 1
    fi
fi

# --- 3. Install fish-speech + huggingface_hub ---------------------------
echo "Installing fish_speech + huggingface_hub..."
if ! "$venv_py" -m pip install --upgrade fish-speech huggingface_hub; then
    echo "! 'pip install fish-speech' failed."
    echo "  Trying source install from GitHub instead..."
    if ! "$venv_py" -m pip install --upgrade \
            "fish-speech @ git+https://github.com/fishaudio/fish-speech.git"; then
        echo "✗ Could not install fish-speech from PyPI or git." >&2
        echo "  Listen-Claude will use the fallback engine." >&2
        exit 1
    fi
fi

# --- 4. Download model checkpoints -------------------------------------
mkdir -p "$model_dir"

have_all=1
for f in firefly-gan-vq-fsq-8x1024-21hz-generator.pth tokenizer.tiktoken; do
    [[ -f "$model_dir/$f" ]] || have_all=0
done

if (( have_all == 1 )); then
    echo "✓ Model already at $model_dir"
else
    echo "Downloading fish-speech-1.5 checkpoints (~2 GB)..."
    if ! "$venv_py" -m huggingface_hub.commands.huggingface_cli download \
            "fishaudio/fish-speech-1.5" \
            --local-dir "$model_dir"; then
        echo "✗ Checkpoint download failed." >&2
        echo "  Likely cause: HuggingFace gating — go to" >&2
        echo "  https://huggingface.co/fishaudio/fish-speech-1.5 and accept the license," >&2
        echo "  then run 'huggingface-cli login' with a read token and re-run this script." >&2
        exit 1
    fi
fi

# --- 5. Verify ----------------------------------------------------------
echo
echo "Verifying installation..."
"$venv_py" - <<'PY'
import torch, fish_speech
print('  torch       =', torch.__version__, '(cuda available:', torch.cuda.is_available(), ')')
print('  fish_speech =', getattr(fish_speech, '__version__', '?'))
PY
status=$?
if (( status == 0 )); then
    echo
    echo "=== Done ==="
    echo "Next steps:"
    echo "  1. Edit .env: set TTS_ENGINE=fish (and optionally FISH_MODEL_DIR=$model_dir)"
    echo "  2. (Optional) point FISH_REFERENCE_VOICE at a 10-30s WAV to clone a voice"
    echo "  3. Open a new Claude Code session — the first response triggers"
    echo "     a ~10 s server cold-start, subsequent responses are <2 s."
else
    echo "✗ Verification failed. Check the errors above." >&2
    exit 1
fi
