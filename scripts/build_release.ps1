param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [int]$ConfigSchema = 2,
    [Parameter(Mandatory = $true)]
    [string]$WinSWPath,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot "build\release"
$Stage = Join-Path $BuildRoot "package"
$PyInstallerDist = Join-Path $BuildRoot "pyinstaller-dist"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller-work"
$BuiltApp = Join-Path $PyInstallerDist "AerotechDocflowApp"
$DistRoot = Join-Path $ProjectRoot "dist"
$ReleaseZip = Join-Path $DistRoot "aerotech-docflow-v$Version.zip"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content + "`n", $Utf8NoBom)
}

if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$') {
    throw "Version must be a valid SemVer without a v prefix: $Version"
}
if ($ConfigSchema -lt 1) {
    throw "ConfigSchema must be >= 1."
}
$WinSWPath = [IO.Path]::GetFullPath($WinSWPath)
if (-not (Test-Path -LiteralPath $WinSWPath -PathType Leaf)) {
    throw "WinSW executable not found: $WinSWPath"
}

Set-Location $ProjectRoot
& $Python -m tests.unit.run_all_unit_tests
if ($LASTEXITCODE -ne 0) {
    throw "Unit tests failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $Stage "app") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "service") -Force | Out-Null
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null

# Remove only exact artifacts from the retired package layout. Keeping them
# beside the new versioned ZIP would leave two competing installation methods.
foreach ($LegacyArtifact in @(
    (Join-Path $DistRoot "AerotechDocflow"),
    (Join-Path $DistRoot "dist.zip"),
    (Join-Path $DistRoot "dist.zip.sha256")
)) {
    $ResolvedLegacy = [IO.Path]::GetFullPath($LegacyArtifact)
    $ResolvedDist = [IO.Path]::GetFullPath($DistRoot).TrimEnd('\') + '\'
    if (-not $ResolvedLegacy.StartsWith($ResolvedDist, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove legacy artifact outside dist: $ResolvedLegacy"
    }
    if (Test-Path -LiteralPath $ResolvedLegacy) {
        Remove-Item -LiteralPath $ResolvedLegacy -Recurse -Force
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --distpath $PyInstallerDist `
    --workpath $PyInstallerWork `
    "packaging\docflow.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath (Join-Path $BuiltApp "aerotech-docflow.exe") -PathType Leaf)) {
    throw "PyInstaller output is incomplete: $BuiltApp"
}

Copy-Item -Path (Join-Path $BuiltApp "*") -Destination (Join-Path $Stage "app") -Recurse -Force
Copy-Item -LiteralPath $WinSWPath -Destination (Join-Path $Stage "service\docflow-service.exe")
Copy-Item -LiteralPath "packaging\service\docflow-service.xml.template" -Destination (Join-Path $Stage "service")

$VersionDocument = [ordered]@{
    version = $Version
    config_schema = $ConfigSchema
} | ConvertTo-Json
Write-Utf8NoBom (Join-Path $Stage "version.json") $VersionDocument

$FilesByPath = @{}
$RelativePaths = [string[]]@(
    Get-ChildItem -LiteralPath $Stage -Recurse -File |
        Where-Object { $_.Name -ne "build-manifest.json" } |
        ForEach-Object {
            $Relative = $_.FullName.Substring($Stage.Length + 1).Replace('\', '/')
            $FilesByPath[$Relative] = $_
            $Relative
        }
)
[Array]::Sort($RelativePaths, [StringComparer]::Ordinal)
$Manifest = @(
    foreach ($Relative in $RelativePaths) {
        $File = $FilesByPath[$Relative]
        [pscustomobject][ordered]@{
            path = $Relative
            size = [Int64]$File.Length
            sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)
Write-Utf8NoBom (Join-Path $Stage "build-manifest.json") ($Manifest | ConvertTo-Json -Depth 3)

if (Test-Path -LiteralPath $ReleaseZip) {
    Remove-Item -LiteralPath $ReleaseZip -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$ArchiveCreated = $false
for ($Attempt = 1; $Attempt -le 10; $Attempt++) {
    try {
        if (Test-Path -LiteralPath $ReleaseZip) {
            Remove-Item -LiteralPath $ReleaseZip -Force
        }
        [IO.Compression.ZipFile]::CreateFromDirectory(
            $Stage,
            $ReleaseZip,
            [IO.Compression.CompressionLevel]::Optimal,
            $false
        )
        $ArchiveCreated = $true
        break
    } catch [IO.IOException] {
        if ($Attempt -eq 10) {
            throw
        }
        Start-Sleep -Seconds 1
    }
}
if (-not $ArchiveCreated) {
    throw "Release ZIP was not created."
}

& $Python -c "from pathlib import Path; import sys; from updater.package import validate_package; p=validate_package(Path(sys.argv[1])); print(p.version.version)" $ReleaseZip
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $ReleaseZip -Force -ErrorAction SilentlyContinue
    throw "Final release ZIP validation failed."
}

$ReleaseHash = (Get-FileHash -LiteralPath $ReleaseZip -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Release ready: $ReleaseZip"
Write-Host "Version: $Version"
Write-Host "Config schema: $ConfigSchema"
Write-Host "SHA-256: $ReleaseHash"
