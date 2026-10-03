# Managed by Codex TPS
$ErrorActionPreference = 'Stop'
$tpsArguments = @($args)
try {
    $tpsConfigPath = Join-Path $PSScriptRoot 'tpscode-install.json'
    $tpsConfig = Get-Content -LiteralPath $tpsConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($tpsConfig.managedBy -ne 'codex-tps-local-installer') {
        throw 'The tpscode installation record is invalid.'
    }
    $tpsSourceDir = [IO.Path]::GetFullPath([string]$tpsConfig.source)
    if (-not (Test-Path -LiteralPath (Join-Path $tpsSourceDir 'codex_tps.py') -PathType Leaf)) {
        throw "Could not locate Codex TPS at: $tpsSourceDir. Run install-command.ps1 from the tool folder."
    }
    if ($tpsArguments.Count -eq 0) {
        & (Join-Path $tpsSourceDir 'Start-Codex-TPS.cmd')
    } else {
        & (Join-Path $tpsSourceDir 'tps.cmd') @tpsArguments
    }
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
