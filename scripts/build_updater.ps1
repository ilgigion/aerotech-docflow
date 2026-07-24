param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildDist = Join-Path $ProjectRoot "build\updater-dist"
$BuildWork = Join-Path $ProjectRoot "build\updater-work"
$Output = Join-Path $ProjectRoot "dist\updater"

if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Updater Version must be major.minor.patch: $Version"
}

Set-Location $ProjectRoot
& $Python -m tests.unit.run_all_unit_tests
if ($LASTEXITCODE -ne 0) {
    throw "Unit tests failed with exit code $LASTEXITCODE"
}

foreach ($Directory in @($BuildDist, $BuildWork, $Output)) {
    if (Test-Path -LiteralPath $Directory) {
        Remove-Item -LiteralPath $Directory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}

$env:AEROTECH_UPDATER_VERSION = $Version
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --distpath $BuildDist `
        --workpath (Join-Path $BuildWork "updater") `
        "packaging\updater.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "AerotechUpdater PyInstaller build failed."
    }
    & $Python -m PyInstaller `
        --noconfirm `
        --distpath $BuildDist `
        --workpath (Join-Path $BuildWork "setup") `
        "packaging\updater-setup.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "AerotechUpdaterSetup PyInstaller build failed."
    }
} finally {
    Remove-Item Env:AEROTECH_UPDATER_VERSION -ErrorAction SilentlyContinue
}

foreach ($Name in @("AerotechUpdater.exe", "AerotechUpdaterSetup.exe")) {
    $Source = Join-Path $BuildDist $Name
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Updater build output missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination (Join-Path $Output $Name)
    $Hash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "$Name SHA-256: $Hash"
}
Write-Host "Updater artifacts: $Output"
