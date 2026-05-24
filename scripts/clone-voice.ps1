# Listen-Claude voice cloning pipeline wrapper.
# Forwards everything to scripts/clone-voice.py under the main venv.
#
# Usage examples:
#   .\scripts\clone-voice.ps1 list
#   .\scripts\clone-voice.ps1 pipeline my-voice https://instagram.com/reel/XYZ
#   .\scripts\clone-voice.ps1 slice my-voice
#   .\scripts\clone-voice.ps1 train my-voice --epochs 15
#   .\scripts\clone-voice.ps1 ref my-voice source/<file>.wav --start 1.0 --end 8.5 --text "..."
#   .\scripts\clone-voice.ps1 activate my-voice

$ErrorActionPreference = 'Stop'
$repoDir   = Split-Path -Parent $PSScriptRoot
$venvPy    = Join-Path $repoDir '.venv\Scripts\python.exe'
$script    = Join-Path $repoDir 'scripts\clone-voice.py'

if (-not (Test-Path $venvPy)) {
    Write-Host "Main venv not found at $venvPy — run install.ps1 first" -ForegroundColor Red
    exit 1
}

& $venvPy $script @args
exit $LASTEXITCODE
