# Play a batch of .wav files back-to-back from the user's own audio
# session — use this from a real PowerShell window when you need to
# listen to test renders. Claude Code tool subprocesses can't reach
# the speakers, so playing from here is the reliable path.
#
# Usage:
#   .\scripts\play-wavs.ps1                         # all voices\_test\*.wav, alphabetical
#   .\scripts\play-wavs.ps1 -Pattern 'diag-*.wav'   # filter by glob
#   .\scripts\play-wavs.ps1 -Dir 'voices\_test'     # different folder
#   .\scripts\play-wavs.ps1 -GapMs 1500             # longer silence between clips

param(
    [string]$Dir = 'voices\_test',
    [string]$Pattern = '*.wav',
    [int]$GapMs = 800
)

$ErrorActionPreference = 'Stop'

# Resolve the directory relative to the repo root, not the caller's
# pwd, so the script works no matter where you cd'd to before running.
$repoDir = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($Dir)) {
    $absDir = $Dir
} else {
    $absDir = Join-Path $repoDir $Dir
}

if (-not (Test-Path $absDir)) {
    Write-Host "no such directory: $absDir" -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem -Path $absDir -Filter $Pattern -File | Sort-Object Name
if ($files.Count -eq 0) {
    Write-Host "no files matching '$Pattern' under $absDir" -ForegroundColor Yellow
    exit 0
}

Write-Host "playing $($files.Count) file(s) from $absDir"
Write-Host ('-' * 60)

$player = New-Object System.Media.SoundPlayer
foreach ($f in $files) {
    Write-Host ('  >>> {0}' -f $f.Name)
    $player.SoundLocation = $f.FullName
    try {
        $player.PlaySync()
    } catch {
        Write-Host ('      playback failed: ' + $_.Exception.Message) -ForegroundColor Red
    }
    if ($GapMs -gt 0) {
        Start-Sleep -Milliseconds $GapMs
    }
}
Write-Host 'done'
