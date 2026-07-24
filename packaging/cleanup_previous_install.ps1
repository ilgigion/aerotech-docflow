$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_paths.ps1")

$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from PowerShell opened with Run as administrator."
}

$InstallDir = Get-CanonicalDocflowInstallDirectory
$DataRoot = Join-Path $env:ProgramData "Aerotech Docflow"
$ServiceName = "AerotechDocflow"

Write-Host "This removes only the previous Aerotech Docflow installation."
Write-Host "Archive roots, PDF files and archive marker files will not be changed."

$Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Service -and $Service.Status -ne "Stopped") {
    Stop-Service -Name $ServiceName -Force
    $Service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}

foreach ($Name in @("aerotech-docflow", "docflow-service")) {
    Get-Process -Name $Name -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force
}

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    & "$env:SystemRoot\System32\sc.exe" delete $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot delete Windows service $ServiceName (sc.exe exit $LASTEXITCODE)."
    }
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        throw "Service is marked for deletion. Restart Windows, then run this script again."
    }
}

if (Test-Path -LiteralPath $InstallDir -PathType Container) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
if (Test-Path -LiteralPath $DataRoot -PathType Container) {
    Remove-Item -LiteralPath $DataRoot -Recurse -Force
}

Write-Host "PREVIOUS INSTALLATION REMOVED"
Write-Host "All archives were preserved."
