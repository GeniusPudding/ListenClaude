# Control Listen-Claude TTS: on/off + reading mode.
# Usage:
#   .\scripts\toggle.ps1                  toggle current on/off state
#   .\scripts\toggle.ps1 on               force on
#   .\scripts\toggle.ps1 off              force off
#   .\scripts\toggle.ps1 status           print on/off state
#   .\scripts\toggle.ps1 llm              Claude-rewritten spoken summary (TTS_MODE=llm)
#   .\scripts\toggle.ps1 smart            alias for llm
#   .\scripts\toggle.ps1 brief            short reading (TTS_MODE=first)
#   .\scripts\toggle.ps1 progress         intro + bullets (TTS_MODE=progress)
#   .\scripts\toggle.ps1 summary          first sentence per paragraph
#   .\scripts\toggle.ps1 detailed         read everything (TTS_MODE=full)
#   .\scripts\toggle.ps1 mode             print current mode

param([string]$Action = 'toggle')

$repoDir = Split-Path -Parent $PSScriptRoot
$marker  = Join-Path $env:TEMP 'listen-claude.disabled'
$envFile = Join-Path $repoDir '.env'

# Aliases that map user-friendly words to TTS_MODE values.
$aliases = @{
    'brief'    = 'first'
    'short'    = 'first'
    'detailed' = 'full'
    'long'     = 'full'
    'smart'    = 'llm'
}
$validModes = @('first', 'progress', 'summary', 'full', 'llm')
# Engine quick-switch aliases. `auto` = hybrid router (Chinese →
# cloned voice via gptsovits, English-heavy → edge). `edge` /
# `default` / `xiaoxiao` snap back to the always-clear Edge voice.
$engineAliases = @{
    'default'      = 'edge'
    'xiaoxiao'     = 'edge'
    'cloned'       = 'auto'
    'hybrid'       = 'auto'
    'ex'           = 'gptsovits'
    'experimental' = 'gptsovits'
    'ig'           = 'gptsovits'
}
$validEngines = @('edge', 'system', 'piper', 'elevenlabs', 'fish', 'gptsovits', 'auto')

$action = $Action.ToLower()
if ($aliases.ContainsKey($action)) { $action = $aliases[$action] }
if ($engineAliases.ContainsKey($action)) { $action = $engineAliases[$action] }

function Set-Mode($mode) {
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $repoDir '.env.example') $envFile -ErrorAction SilentlyContinue
    }
    if (Test-Path $envFile) {
        $kept = @(Get-Content $envFile) | Where-Object { $_ -notmatch '^\s*TTS_MODE\s*=' }
        $kept + "TTS_MODE=$mode" | Set-Content -Path $envFile -Encoding UTF8
    }
    Write-Host "Listen-Claude mode: $mode"
}

function Set-Engine($engine) {
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $repoDir '.env.example') $envFile -ErrorAction SilentlyContinue
    }
    if (Test-Path $envFile) {
        $kept = @(Get-Content $envFile) | Where-Object { $_ -notmatch '^\s*TTS_ENGINE\s*=' }
        $kept + "TTS_ENGINE=$engine" | Set-Content -Path $envFile -Encoding UTF8
    }
    Write-Host "Listen-Claude engine: $engine"
}

function Get-Engine {
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*TTS_ENGINE\s*=\s*(.+?)\s*$') { return $matches[1] }
        }
    }
    return 'edge (default)'
}

function Get-Mode {
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*TTS_MODE\s*=\s*(.+?)\s*$') { return $matches[1] }
        }
    }
    return 'progress (default)'
}

# Mode setters.
if ($validModes -contains $action) { Set-Mode $action; exit 0 }
if ($action -eq 'mode')             { Write-Host "Listen-Claude mode: $(Get-Mode)"; exit 0 }

# Engine setters / inspector.
if ($validEngines -contains $action) { Set-Engine $action; exit 0 }
if ($action -eq 'engine')            { Write-Host "Listen-Claude engine: $(Get-Engine)"; exit 0 }

# on/off/status/toggle.
$exists = Test-Path $marker
switch ($action) {
    'on'     { if ($exists) { Remove-Item $marker -Force }; $state = 'ON' }
    'off'    { if (-not $exists) { New-Item -ItemType File -Path $marker -Force | Out-Null }; $state = 'OFF' }
    'status' { $state = if ($exists) { 'OFF' } else { 'ON' } }
    default  {
        if ($exists) { Remove-Item $marker -Force; $state = 'ON' }
        else         { New-Item -ItemType File -Path $marker -Force | Out-Null; $state = 'OFF' }
    }
}
Write-Host "Listen-Claude TTS: $state"
