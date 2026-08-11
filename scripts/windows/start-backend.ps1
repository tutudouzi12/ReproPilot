param([string]$Python = "py")

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $name = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Import-DotEnv -Path (Join-Path $root "backend.env")
Set-Location (Join-Path $root "backend")

if ($Python -eq "py") {
    & py -3.11 run.py
} else {
    & $Python run.py
}
