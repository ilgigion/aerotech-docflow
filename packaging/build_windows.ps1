param(
    [string]$Python = "python",
    [string]$WinSWPath = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $ProjectRoot "dist"
$Package = Join-Path $DistRoot "AerotechDocflow"
$PyInstallerDist = Join-Path $ProjectRoot "build\pyinstaller-dist"
$BuiltApp = Join-Path $PyInstallerDist "AerotechDocflowApp"
$PackageApp = Join-Path $Package "app"
$PackageConfig = Join-Path $Package "config"
$PackageService = Join-Path $Package "service"
$PackageDocs = Join-Path $Package "docs"
$ReleaseZip = Join-Path $DistRoot "dist.zip"
$ReleaseZipHash = Join-Path $DistRoot "dist.zip.sha256"

Set-Location $ProjectRoot

if ($Clean) {
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot "build")) {
        Remove-Item -LiteralPath (Join-Path $ProjectRoot "build") -Recurse -Force
    }
    if (Test-Path -LiteralPath $Package) {
        Remove-Item -LiteralPath $Package -Recurse -Force
    }
    foreach ($ReleaseArtifact in @($ReleaseZip, $ReleaseZipHash)) {
        if (Test-Path -LiteralPath $ReleaseArtifact) {
            Remove-Item -LiteralPath $ReleaseArtifact -Force
        }
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --distpath $PyInstallerDist `
    --workpath (Join-Path $ProjectRoot "build\pyinstaller-work") `
    "packaging\docflow.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath (Join-Path $BuiltApp "aerotech-docflow.exe") -PathType Leaf)) {
    throw "PyInstaller output is incomplete: $BuiltApp"
}

# Always assemble the distributable from an empty directory. Otherwise a
# wrapper or library from an older build could silently survive an incremental
# build and end up in the manifest.
if (Test-Path -LiteralPath $Package) {
    Remove-Item -LiteralPath $Package -Recurse -Force
}
foreach ($Directory in @($PackageApp, $PackageConfig, $PackageService, $PackageDocs)) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}

Copy-Item -Path (Join-Path $BuiltApp "*") -Destination $PackageApp -Recurse -Force
Copy-Item -LiteralPath "config.example.toml" -Destination (Join-Path $PackageConfig "config.example.toml") -Force
$ProductionTemplate = "packaging\config.production.example.toml"
# The editable package copy keeps the historical config.production.toml name,
# while the second copy remains an untouched reference for recovery/comparison.
Copy-Item -LiteralPath $ProductionTemplate -Destination (Join-Path $PackageConfig "config.production.toml") -Force
Copy-Item -LiteralPath $ProductionTemplate -Destination (Join-Path $PackageConfig "config.production.example.toml") -Force
Copy-Item -LiteralPath "packaging\service\docflow-service.xml.template" -Destination $PackageService -Force
Copy-Item -LiteralPath "packaging\service\install-service.ps1" -Destination $PackageService -Force
Copy-Item -LiteralPath "packaging\service\uninstall-service.ps1" -Destination $PackageService -Force
Copy-Item -LiteralPath "packaging\cleanup_previous_install.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "packaging\common_paths.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "packaging\install_current_machine.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "packaging\update.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "packaging\update-helper.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "packaging\start-manually.ps1" -Destination $Package -Force
Copy-Item -LiteralPath "docs\10_WINDOWS_INSTALLATION_AND_SERVICE.md" -Destination (Join-Path $PackageDocs "INSTALLATION.md") -Force
Copy-Item -LiteralPath "docs\11_CLEAN_INSTALLATION.md" -Destination (Join-Path $PackageDocs "START_HERE.md") -Force
Copy-Item -LiteralPath "docs\guide" -Destination (Join-Path $PackageDocs "guide") -Recurse -Force

if ($WinSWPath) {
    if (-not (Test-Path -LiteralPath $WinSWPath -PathType Leaf)) {
        throw "WinSW executable not found: $WinSWPath"
    }
    $ResolvedWinSW = (Resolve-Path -LiteralPath $WinSWPath).Path
    Copy-Item -LiteralPath $ResolvedWinSW -Destination (Join-Path $PackageService "docflow-service.exe") -Force
    $WinSWHash = (Get-FileHash -LiteralPath $ResolvedWinSW -Algorithm SHA256).Hash
    Set-Content -LiteralPath (Join-Path $PackageService "WinSW.sha256") -Value "$WinSWHash  docflow-service.exe" -Encoding ASCII
} else {
    Write-Warning "WinSW was not supplied. The app is built, but service installation requires service\docflow-service.exe."
}

$Files = Get-ChildItem -LiteralPath $Package -Recurse -File | ForEach-Object {
    [pscustomobject]@{
        Path = $_.FullName.Substring($Package.Length + 1)
        Size = $_.Length
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$Files | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $Package "build-manifest.json") -Encoding UTF8

foreach ($ReleaseArtifact in @($ReleaseZip, $ReleaseZipHash)) {
    if (Test-Path -LiteralPath $ReleaseArtifact) {
        Remove-Item -LiteralPath $ReleaseArtifact -Force
    }
}
Compress-Archive -Path (Join-Path $Package "*") -DestinationPath $ReleaseZip -CompressionLevel Optimal
$ReleaseHash = (Get-FileHash -LiteralPath $ReleaseZip -Algorithm SHA256).Hash
Set-Content -LiteralPath $ReleaseZipHash -Value "$ReleaseHash  dist.zip" -Encoding ASCII

Write-Host "Package ready: $Package"
Write-Host "GitHub Release asset: $ReleaseZip"
Write-Host "SHA-256: $ReleaseZipHash"
Write-Host "Test: & `"$Package\app\aerotech-docflow.exe`" --config `"$Package\config\config.example.toml`" show-config"
