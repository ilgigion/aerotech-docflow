$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:ProgramFiles "Aerotech Docflow"
$Config = Join-Path $env:ProgramData "Aerotech Docflow\config\config.toml"
$Executable = Join-Path $InstallDir "app\aerotech-docflow.exe"

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Application is not installed: $Executable"
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "Configuration is not installed: $Config"
}

& $Executable --config $Config run
exit $LASTEXITCODE
