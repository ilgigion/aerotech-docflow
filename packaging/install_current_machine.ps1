param(
    [string]$ConfigSource = "",
    [switch]$ConfirmArchive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_paths.ps1")
$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from PowerShell opened with Run as administrator."
}
if (-not $ConfirmArchive) {
    throw "Review the archive path in config.production.toml and rerun with -ConfirmArchive."
}

$PackageRoot = $PSScriptRoot
$InstallDir = Get-CanonicalDocflowInstallDirectory
Assert-NoLegacyX86DocflowInstallation
$DataRoot = Join-Path $env:ProgramData "Aerotech Docflow"
if (-not $ConfigSource) {
    $ConfigSource = Join-Path $PackageRoot "config\config.production.toml"
}
$ConfigSource = [IO.Path]::GetFullPath($ConfigSource)
$ConfigTarget = Join-Path $DataRoot "config\config.toml"
$SourceExecutable = Join-Path $PackageRoot "app\aerotech-docflow.exe"

foreach ($RequiredFile in @(
    $SourceExecutable,
    $ConfigSource
)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required file not found: $RequiredFile"
    }
}

$ConfigReportText = & $SourceExecutable --config $ConfigSource show-config --ascii | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Cannot read installation configuration: $ConfigSource"
}
$ConfigReport = $ConfigReportText | ConvertFrom-Json
if (@($ConfigReport.overridden_by_environment).Count -gt 0) {
    throw (
        "Installation configuration is overridden by process environment variables: " +
        (@($ConfigReport.overridden_by_environment) -join ", ")
    )
}
$Effective = $ConfigReport.effective_environment
$ArchiveRoot = [string]$Effective.ARCHIVE_ROOT
$ArchiveConfirmation = [string]$Effective.DOCFLOW_ARCHIVE_CONFIRMATION
$ArchiveId = [string]$Effective.DOCFLOW_ARCHIVE_ID
$Incoming = [string]$Effective.SCANNER_INCOMING_DIR
$Naps2 = [string]$Effective.NAPS2_EXECUTABLE
$LogDir = [string]$Effective.DOCFLOW_LOG_DIR
$IdempotencyDir = [string]$Effective.DOCFLOW_IDEMPOTENCY_DIR

foreach ($RequiredSetting in @{
    "archive.root" = $ArchiveRoot
    "archive.confirmation" = $ArchiveConfirmation
    "archive.archive_id" = $ArchiveId
    "scanner.incoming_dir" = $Incoming
    "scanner.naps2_executable" = $Naps2
    "logging.directory" = $LogDir
    "idempotency.directory" = $IdempotencyDir
}.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace([string]$RequiredSetting.Value)) {
        throw "Required installation setting is empty: $($RequiredSetting.Key)"
    }
}

$ResolvedArchive = [IO.Path]::GetFullPath($ArchiveRoot).TrimEnd('\')
$ResolvedConfirmation = [IO.Path]::GetFullPath($ArchiveConfirmation).TrimEnd('\')
if ($ResolvedArchive -ne $ResolvedConfirmation) {
    throw "archive.root and archive.confirmation must resolve to the same directory."
}
$MarkerTarget = Join-Path $ResolvedArchive ".aerotech-docflow-archive.json"

if (-not (Test-Path -LiteralPath $ArchiveRoot -PathType Container)) {
    throw "Archive root does not exist: $ArchiveRoot"
}
if (-not (Test-Path -LiteralPath $Naps2 -PathType Leaf)) {
    throw "NAPS2 executable does not exist: $Naps2"
}
if (Get-Service -Name "AerotechDocflow" -ErrorAction SilentlyContinue) {
    throw "Old AerotechDocflow service still exists. Run cleanup_previous_install.ps1 first."
}
if ((Test-Path -LiteralPath $InstallDir -PathType Container) -and
    (Get-ChildItem -LiteralPath $InstallDir -Force | Select-Object -First 1)) {
    throw "Install directory is not empty. Run cleanup_previous_install.ps1 first: $InstallDir"
}
if (Test-Path -LiteralPath $ConfigTarget -PathType Leaf) {
    throw "Configuration already exists. Run cleanup_previous_install.ps1 first: $ConfigTarget"
}

if (Test-Path -LiteralPath $MarkerTarget -PathType Leaf) {
    $MarkerData = Get-Content -LiteralPath $MarkerTarget -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($MarkerData.marker -ne "aerotech-docflow-archive-v1" -or
        $MarkerData.archive_id -ne $ArchiveId) {
        throw "Existing archive marker identity does not match: $MarkerTarget"
    }
}

foreach ($Directory in @(
    $InstallDir,
    (Join-Path $DataRoot "config"),
    (Join-Path $DataRoot "service-logs"),
    $Incoming,
    $LogDir,
    $IdempotencyDir
)) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}

Copy-Item -Path (Join-Path $PackageRoot "*") -Destination $InstallDir -Recurse -Force
Copy-Item -LiteralPath $ConfigSource -Destination $ConfigTarget
if (-not (Test-Path -LiteralPath $MarkerTarget -PathType Leaf)) {
    $MarkerJson = [ordered]@{
        marker = "aerotech-docflow-archive-v1"
        archive_id = $ArchiveId
    } | ConvertTo-Json
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($MarkerTarget, $MarkerJson + "`n", $Utf8NoBom)
}

$Executable = Join-Path $InstallDir "app\aerotech-docflow.exe"
& $Executable --config $ConfigTarget preflight
if ($LASTEXITCODE -ne 0) {
    throw "Installation copied files, but production preflight failed. Do not start the API."
}

Write-Host "INSTALLATION FILES READY"
Write-Host "No Windows service was created."
Write-Host "Next run: $InstallDir\start-manually.ps1"
