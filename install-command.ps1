$ErrorActionPreference = 'Stop'

# Registers this tool directory. No network or admin rights.
$tpsBinDir = Join-Path $env:USERPROFILE '.local/bin'
$tpsCommandPath = Join-Path $tpsBinDir 'tpscode.cmd'
$tpsShellPath = Join-Path $tpsBinDir 'tpscode'
$tpsScriptPath = Join-Path $tpsBinDir 'tpscode-launch.ps1'
$tpsManifestPath = Join-Path $tpsBinDir 'tpscode-install.json'
$tpsFileNames = @('codex_tps.py', 'desktop.py', 'launch.pyw', 'window_instance.py', 'Start-Codex-TPS.cmd', 'tps.cmd', 'README.md')

function Copy-TpsAtomic {
    param([string]$tpsCopySource, [string]$tpsCopyTarget)
    $tpsStagingPath = $tpsCopyTarget + '.install-' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        Copy-Item -LiteralPath $tpsCopySource -Destination $tpsStagingPath
        if (Test-Path -LiteralPath $tpsCopyTarget -PathType Leaf) {
            [IO.File]::Replace($tpsStagingPath, $tpsCopyTarget, [NullString]::Value)
        } else {
            [IO.File]::Move($tpsStagingPath, $tpsCopyTarget)
        }
    } finally {
        # This unique staging file is created by this installer only.
        if (Test-Path -LiteralPath $tpsStagingPath -PathType Leaf) {
            Remove-Item -LiteralPath $tpsStagingPath
        }
    }
}

foreach ($tpsFileName in $tpsFileNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $tpsFileName) -PathType Leaf)) {
        throw "Missing application file: $tpsFileName"
    }
}
foreach ($tpsLauncherName in @('global-launch.cmd', 'global-launch.ps1', 'global-launch.sh')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $tpsLauncherName) -PathType Leaf)) {
        throw "Missing launcher file: $tpsLauncherName"
    }
}

if (Test-Path -LiteralPath $tpsCommandPath) {
    $tpsExistingLauncher = Get-Content -LiteralPath $tpsCommandPath -Raw
    if ($tpsExistingLauncher -notmatch '(?m)^rem Managed by Codex TPS\r?$') {
        throw 'An unrelated tpscode.cmd already exists. It has not been changed.'
    }
}
if (Test-Path -LiteralPath $tpsShellPath) {
    $tpsExistingShell = Get-Content -LiteralPath $tpsShellPath -Raw
    if ($tpsExistingShell -notmatch '(?m)^# Managed by Codex TPS\r?$') {
        throw 'An unrelated tpscode shell command already exists. It has not been changed.'
    }
}
if (Test-Path -LiteralPath $tpsScriptPath) {
    $tpsExistingScript = Get-Content -LiteralPath $tpsScriptPath -Raw
    if ($tpsExistingScript -notmatch '(?m)^# Managed by Codex TPS\r?$') {
        throw 'An unrelated tpscode-launch.ps1 already exists. It has not been changed.'
    }
}
if (Test-Path -LiteralPath $tpsManifestPath) {
    $tpsExistingManifest = Get-Content -LiteralPath $tpsManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($tpsExistingManifest.managedBy -ne 'codex-tps-local-installer') {
        throw 'The existing tpscode installation record belongs to another application. It has not been changed.'
    }
}

[void](New-Item -ItemType Directory -Path $tpsBinDir -Force)
$tpsManifest = [ordered]@{
    managedBy = 'codex-tps-local-installer'
    source = $PSScriptRoot
    installedAt = [DateTimeOffset]::UtcNow.ToString('o')
    command = $tpsCommandPath
}
$tpsManifestStaging = $tpsManifestPath + '.source-' + [Guid]::NewGuid().ToString('N') + '.tmp'
try {
    $tpsManifest | ConvertTo-Json | Set-Content -LiteralPath $tpsManifestStaging -Encoding UTF8
    Copy-TpsAtomic -tpsCopySource $tpsManifestStaging -tpsCopyTarget $tpsManifestPath
} finally {
    if (Test-Path -LiteralPath $tpsManifestStaging -PathType Leaf) {
        Remove-Item -LiteralPath $tpsManifestStaging
    }
}
Copy-TpsAtomic -tpsCopySource (Join-Path $PSScriptRoot 'global-launch.ps1') -tpsCopyTarget $tpsScriptPath
Copy-TpsAtomic -tpsCopySource (Join-Path $PSScriptRoot 'global-launch.cmd') -tpsCopyTarget $tpsCommandPath
Copy-TpsAtomic -tpsCopySource (Join-Path $PSScriptRoot 'global-launch.sh') -tpsCopyTarget $tpsShellPath

$tpsUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$tpsPathParts = @($tpsUserPath -split ';' | Where-Object { $_ })
$tpsPathPresent = @($tpsPathParts | Where-Object {
    [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\', '/') -eq $tpsBinDir.TrimEnd('\', '/')
}).Count -gt 0
if (-not $tpsPathPresent) {
    $tpsUpdatedPath = (@($tpsPathParts) + $tpsBinDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $tpsUpdatedPath, 'User')
}
# Keep this installer process usable immediately; no persistent overwrite of
# other PATH entries, and no change when the directory is already registered.
if (-not (@($env:Path -split ';' | Where-Object { $_.TrimEnd('\', '/') -eq $tpsBinDir.TrimEnd('\', '/') }).Count -gt 0)) {
    $env:Path = $env:Path.TrimEnd(';') + ';' + $tpsBinDir
}
Write-Output 'Installed: tpscode (read-only logs), tpscode gui, tpscode list, tpscode watch'
Write-Output "App: $PSScriptRoot"
Write-Output "Command: $tpsCommandPath"
if (-not $tpsPathPresent) {
    Write-Output 'Open a new terminal for the added PATH entry.'
}
