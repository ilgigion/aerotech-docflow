param(
    [string]$InstallDir = "$env:ProgramFiles\Aerotech Docflow",
    [string]$ConfigPath = "$env:ProgramData\Aerotech Docflow\config\config.toml",
    [ValidateSet("Prompt", "LocalService", "NetworkService", "LocalSystem")]
    [string]$ServiceAccountMode = "Prompt",
    [switch]$StartService
)

$ErrorActionPreference = "Stop"
$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run install-service.ps1 from an elevated PowerShell (Run as Administrator)."
}

$PackageRoot = Split-Path -Parent $PSScriptRoot
$SourceDocflow = Join-Path $PackageRoot "app\aerotech-docflow.exe"
$SourceWrapper = Join-Path $PackageRoot "service\docflow-service.exe"
$SourceTemplate = Join-Path $PackageRoot "service\docflow-service.xml.template"
foreach ($Required in @($SourceDocflow, $SourceWrapper, $SourceTemplate, $ConfigPath)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Required file not found: $Required"
    }
}

$ExistingService = Get-Service -Name "AerotechDocflow" -ErrorAction SilentlyContinue
if ($ExistingService) {
    throw "AerotechDocflow service already exists. Uninstall it before installation or upgrade."
}

$ResolvedPackage = (Resolve-Path -LiteralPath $PackageRoot).Path.TrimEnd('\')
$ResolvedInstall = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
if ($ResolvedPackage -ne $ResolvedInstall) {
    if ((Test-Path -LiteralPath $ResolvedInstall -PathType Container) -and
        (Get-ChildItem -LiteralPath $ResolvedInstall -Force | Select-Object -First 1)) {
        throw "Install directory is not empty: $ResolvedInstall. Use an empty directory to avoid mixing application versions."
    }
    New-Item -ItemType Directory -Path $ResolvedInstall -Force | Out-Null
    Copy-Item -Path (Join-Path $ResolvedPackage "*") -Destination $ResolvedInstall -Recurse -Force
}

$AppDir = Join-Path $ResolvedInstall "app"
$ServiceDir = Join-Path $ResolvedInstall "service"
$DocflowExe = Join-Path $AppDir "aerotech-docflow.exe"
$WrapperExe = Join-Path $ServiceDir "docflow-service.exe"
$Template = Join-Path $ServiceDir "docflow-service.xml.template"
$WrapperXml = Join-Path $ServiceDir "docflow-service.xml"
$ServiceLogDir = Join-Path $env:ProgramData "Aerotech Docflow\service-logs"
New-Item -ItemType Directory -Path $ServiceLogDir -Force | Out-Null

function Escape-Xml([string]$Value) {
    return [Security.SecurityElement]::Escape($Value)
}

switch ($ServiceAccountMode) {
    "Prompt" {
        $ServiceAccount = "<serviceaccount><prompt>console</prompt><allowservicelogon>true</allowservicelogon></serviceaccount>"
    }
    "LocalService" {
        $ServiceAccount = "<serviceaccount><username>NT AUTHORITY\LocalService</username></serviceaccount>"
    }
    "NetworkService" {
        $ServiceAccount = "<serviceaccount><username>NT AUTHORITY\NetworkService</username></serviceaccount>"
    }
    "LocalSystem" {
        $ServiceAccount = "<serviceaccount><username>LocalSystem</username></serviceaccount>"
    }
}

$Xml = Get-Content -LiteralPath $Template -Raw -Encoding UTF8
$Xml = $Xml.Replace("__SERVICE_ACCOUNT__", $ServiceAccount)
$Xml = $Xml.Replace("__DOCFLOW_EXE__", (Escape-Xml $DocflowExe))
$Xml = $Xml.Replace("__CONFIG_PATH__", (Escape-Xml ([IO.Path]::GetFullPath($ConfigPath))))
$Xml = $Xml.Replace("__APP_DIR__", (Escape-Xml $AppDir))
$Xml = $Xml.Replace("__SERVICE_LOG_DIR__", (Escape-Xml $ServiceLogDir))
Set-Content -LiteralPath $WrapperXml -Value $Xml -Encoding UTF8

& $DocflowExe --config $ConfigPath preflight
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $WrapperXml -Force -ErrorAction SilentlyContinue
    throw "Production preflight failed. Service was not installed."
}

& $WrapperExe install
if ($LASTEXITCODE -ne 0) {
    throw "WinSW service installation failed with exit code $LASTEXITCODE"
}

if ($StartService) {
    & $WrapperExe start
    if ($LASTEXITCODE -ne 0) {
        throw "Service was installed but failed to start. Check service-logs and Windows Event Log."
    }
    $EffectiveConfig = (& $DocflowExe --config $ConfigPath show-config --ascii | ConvertFrom-Json)
    $ApiHost = [string]$EffectiveConfig.effective_environment.DOCFLOW_HOST
    $Port = [int]$EffectiveConfig.effective_environment.DOCFLOW_PORT
    $Healthy = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        Start-Sleep -Seconds 1
        try {
            $Health = Invoke-RestMethod -Uri "http://${ApiHost}:$Port/health" -TimeoutSec 2
            if ($Health.status -eq "ok") {
                $Healthy = $true
                break
            }
        } catch {
            # The service may still be starting or may have failed its own preflight.
        }
    }
    if (-not $Healthy) {
        throw "Service was registered but /health did not become ready. Check service-logs and Windows Event Log."
    }
}

Write-Host "Service installed: AerotechDocflow"
Write-Host "Application: $ResolvedInstall"
Write-Host "Configuration: $ConfigPath"
Write-Host "Service logs: $ServiceLogDir"
