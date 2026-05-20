# Install fish-speech into Listen-Claude's venv: PyTorch (CUDA if
# available, else CPU), the fish_speech package, and the 1.5 checkpoints.
# Safe to re-run (idempotent — re-downloads only if files are missing).
#
# Failure modes are loud but non-fatal: the main install.ps1 has already
# set up Listen-Claude with the default Edge engine, so even if this
# script fails halfway, TTS still works — you just don't get the GPU
# voice.

$ErrorActionPreference = 'Continue'

$repoDir   = Split-Path -Parent $PSScriptRoot
$venvDir   = Join-Path $repoDir '.venv'
$venvPy    = Join-Path $venvDir 'Scripts\python.exe'
$modelDir  = if ($env:FISH_MODEL_DIR) { $env:FISH_MODEL_DIR } else { Join-Path $HOME '.cache\fish-speech' }

Write-Host ''
Write-Host '=== install-fish-speech ==='
Write-Host "Repo:       $repoDir"
Write-Host "venv:       $venvDir"
Write-Host "Model dir:  $modelDir"

if (-not (Test-Path $venvPy)) {
    Write-Host "✗ venv not found. Run .\install.ps1 first." -ForegroundColor Red
    exit 1
}

# --- 1. Detect CUDA -----------------------------------------------------
$cudaTag = 'cpu'
$cudaVersion = $null
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    $smiOut = & nvidia-smi 2>&1
    if ($LASTEXITCODE -eq 0) {
        $m = [regex]::Match($smiOut -join "`n", 'CUDA Version:\s*(\d+)\.(\d+)')
        if ($m.Success) {
            $cudaVersion = "$($m.Groups[1].Value).$($m.Groups[2].Value)"
            # PyTorch publishes cu121, cu124, cu118, etc. Pick the closest
            # available wheel tag for the driver's CUDA version.
            $major = [int]$m.Groups[1].Value
            $minor = [int]$m.Groups[2].Value
            # NVIDIA drivers are forward-compatible with older CUDA toolkits,
            # so we always pick the newest PyTorch wheel tag the driver can
            # run. Mapping based on what download.pytorch.org actually ships.
            if     ($major -ge 13)                   { $cudaTag = 'cu128' }
            elseif ($major -ge 12 -and $minor -ge 8) { $cudaTag = 'cu128' }
            elseif ($major -ge 12 -and $minor -ge 4) { $cudaTag = 'cu124' }
            elseif ($major -ge 12)                   { $cudaTag = 'cu121' }
            elseif ($major -ge 11 -and $minor -ge 8) { $cudaTag = 'cu118' }
            else                                     { $cudaTag = 'cu121' }
        }
    }
}

if ($cudaTag -eq 'cpu') {
    Write-Host '! No NVIDIA GPU / CUDA detected — installing CPU-only PyTorch.' -ForegroundColor Yellow
    Write-Host '  fish-speech on CPU is 10-20x slower; Listen-Claude will' -ForegroundColor Yellow
    Write-Host '  still work because TTS_ENGINE=fish auto-falls back to' -ForegroundColor Yellow
    Write-Host '  TTS_FALLBACK_ENGINE (default: edge) when CUDA is missing.' -ForegroundColor Yellow
} else {
    Write-Host "✓ CUDA $cudaVersion detected — installing PyTorch wheel tag '$cudaTag'."
}

# --- 2. Install PyTorch (skip if already present with correct flavor) ---
$torchOk = $false
& $venvPy -c "import torch; print(torch.__version__); print('CUDA' if torch.cuda.is_available() else 'CPU')" 2>$null
if ($LASTEXITCODE -eq 0) {
    $torchOk = $true
    Write-Host '✓ torch already installed in venv.'
}

if (-not $torchOk) {
    Write-Host "Installing torch / torchaudio (tag: $cudaTag)..."
    $idxUrl = "https://download.pytorch.org/whl/$cudaTag"
    & $venvPy -m pip install --upgrade torch torchaudio --index-url $idxUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Host '✗ torch install failed. fish-speech will not work; Listen-Claude will use the fallback engine.' -ForegroundColor Red
        exit 1
    }
}

# --- 3. Install fish-speech + huggingface_hub ---------------------------
Write-Host 'Installing fish_speech + huggingface_hub...'
& $venvPy -m pip install --upgrade fish-speech huggingface_hub
if ($LASTEXITCODE -ne 0) {
    Write-Host '! `pip install fish-speech` failed.' -ForegroundColor Yellow
    Write-Host '  Trying source install from GitHub instead...' -ForegroundColor Yellow
    & $venvPy -m pip install --upgrade 'fish-speech @ git+https://github.com/fishaudio/fish-speech.git'
    if ($LASTEXITCODE -ne 0) {
        Write-Host '✗ Could not install fish-speech from PyPI or git.' -ForegroundColor Red
        Write-Host '  Listen-Claude will use the fallback engine.' -ForegroundColor Red
        exit 1
    }
}

# --- 4. Download model checkpoints -------------------------------------
if (-not (Test-Path $modelDir)) {
    New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
}

# A handful of marker files we expect after a successful download.
$markers = @(
    'firefly-gan-vq-fsq-8x1024-21hz-generator.pth',
    'tokenizer.tiktoken'
) | ForEach-Object { Join-Path $modelDir $_ }
$haveAll = $true
foreach ($m in $markers) { if (-not (Test-Path $m)) { $haveAll = $false } }

if ($haveAll) {
    Write-Host "✓ Model already at $modelDir"
} else {
    Write-Host 'Downloading fish-speech-1.5 checkpoints (~2 GB)...'
    & $venvPy -m huggingface_hub.commands.huggingface_cli download `
        'fishaudio/fish-speech-1.5' `
        --local-dir $modelDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host '✗ Checkpoint download failed.' -ForegroundColor Red
        Write-Host '  Likely cause: HuggingFace gating — go to' -ForegroundColor Red
        Write-Host '  https://huggingface.co/fishaudio/fish-speech-1.5 and accept the license,' -ForegroundColor Red
        Write-Host '  then `huggingface-cli login` with a read token and re-run this script.' -ForegroundColor Red
        exit 1
    }
}

# --- 5. Verify ----------------------------------------------------------
Write-Host ''
Write-Host 'Verifying installation...'
& $venvPy -c @"
import torch, fish_speech
print('  torch       =', torch.__version__, '(cuda available:', torch.cuda.is_available(), ')')
print('  fish_speech =', getattr(fish_speech, '__version__', '?'))
"@
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '=== Done ===' -ForegroundColor Green
    Write-Host 'Next steps:'
    Write-Host "  1. Edit .env: set TTS_ENGINE=fish (and optionally FISH_MODEL_DIR=$modelDir)"
    Write-Host '  2. (Optional) point FISH_REFERENCE_VOICE at a 10-30s WAV to clone a voice'
    Write-Host '  3. Open a new Claude Code session — the first response triggers'
    Write-Host '     a ~10 s server cold-start, subsequent responses are <2 s.'
} else {
    Write-Host '✗ Verification failed. Check the errors above.' -ForegroundColor Red
    exit 1
}
