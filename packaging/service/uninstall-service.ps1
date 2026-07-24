param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "common_paths.ps1")
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Get-CanonicalDocflowInstallDirectory
}
$InstallDir = Assert-CanonicalDocflowInstallDirectory $InstallDir
$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run uninstall-service.ps1 from an elevated PowerShell (Run as Administrator)."
}

$WrapperExe = Join-Path $InstallDir "service\docflow-service.exe"
if (-not (Test-Path -LiteralPath $WrapperExe -PathType Leaf)) {
    throw "WinSW wrapper not found: $WrapperExe"
}

$Service = Get-Service -Name "AerotechDocflow" -ErrorAction SilentlyContinue
if ($Service -and $Service.Status -ne "Stopped") {
    & $WrapperExe stop
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop AerotechDocflow service."
    }
}

if (Get-Service -Name "AerotechDocflow" -ErrorAction SilentlyContinue) {
    & $WrapperExe uninstall
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to uninstall AerotechDocflow service."
    }
}

Write-Host "Service uninstalled."
Write-Host "Application files, config, logs, incoming, idempotency and archive were NOT deleted."
