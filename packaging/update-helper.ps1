param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$TempRoot,
    [Parameter(Mandatory = $true)]
    [string]$ReadyFile,
    [Parameter(Mandatory = $true)]
    [int]$ParentProcessId
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_paths.ps1")
$ServiceName = "AerotechDocflow"
$ConfigPath = Join-Path $env:ProgramData "Aerotech Docflow\config\config.toml"

function Assert-Administrator {
    $Principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "The update helper must run as administrator."
    }
}

function Test-IsSameOrChildPath([string]$Candidate, [string]$Parent) {
    $FullCandidate = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $FullParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    if ($FullCandidate.Equals($FullParent, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $FullCandidate.StartsWith(
        $FullParent + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-NormalizedFullPath([string]$Path) {
    $FullPath = [IO.Path]::GetFullPath($Path)
    $PathRoot = [IO.Path]::GetPathRoot($FullPath)
    if ($FullPath.Equals($PathRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $PathRoot
    }
    return $FullPath.TrimEnd('\')
}

function Assert-SafeManagedDirectory([string]$Path, [string]$Expected) {
    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $ResolvedExpected = [IO.Path]::GetFullPath($Expected).TrimEnd('\')
    if (-not $Resolved.Equals($ResolvedExpected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing filesystem operation outside the exact managed path: $Resolved"
    }
    if (Test-Path -LiteralPath $Resolved) {
        $Item = Get-Item -LiteralPath $Resolved -Force
        if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing filesystem operation on a reparse point: $Resolved"
        }
    }
    return $Resolved
}

function Remove-SafeManagedDirectory([string]$Path, [string]$Expected) {
    $Resolved = Assert-SafeManagedDirectory $Path $Expected
    if (Test-Path -LiteralPath $Resolved) {
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}

function Remove-PreviousUpdateDirectories([string]$InstallRoot) {
    $Parent = Split-Path -Parent $InstallRoot
    $InstallName = Split-Path -Leaf $InstallRoot
    $NamePattern = '^' + [Regex]::Escape($InstallName) +
        '\.(rollback|failed-update)([-.]\d{8}_\d{6})?$'
    foreach ($Directory in Get-ChildItem -LiteralPath $Parent -Directory -Force) {
        if ($Directory.Name -notmatch $NamePattern) {
            continue
        }
        $Expected = Join-Path $Parent $Directory.Name
        Remove-SafeManagedDirectory $Directory.FullName $Expected
    }
}

function Assert-NoScannerActivity([string]$LockPath) {
    $Naps2Processes = @(Get-Process -Name "NAPS2*" -ErrorAction SilentlyContinue)
    if ($Naps2Processes.Count -gt 0) {
        $Details = ($Naps2Processes | ForEach-Object { "$($_.ProcessName) PID=$($_.Id)" }) -join ", "
        throw "Update refused because NAPS2 is running: $Details"
    }
    if (Test-Path -LiteralPath $LockPath) {
        throw "Update refused because scanner lock exists: $LockPath. Diagnose it; do not delete it blindly."
    }
}

function Get-InstalledApplicationProcesses([string]$InstallRoot) {
    $Matches = @()
    foreach ($Process in @(Get-Process -Name "aerotech-docflow" -ErrorAction SilentlyContinue)) {
        try {
            $ExecutablePath = [string]$Process.Path
        } catch {
            throw "Cannot determine executable path for aerotech-docflow PID=$($Process.Id)."
        }
        if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
            throw "Cannot determine executable path for aerotech-docflow PID=$($Process.Id)."
        }
        if (Test-IsSameOrChildPath $ExecutablePath $InstallRoot) {
            $Matches += $Process
        }
    }
    return @($Matches)
}

function Stop-InstalledRuntime([string]$InstallRoot) {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($Service -and $Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $ServiceName -Force
        $Service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    }
    foreach ($Process in @(Get-InstalledApplicationProcesses $InstallRoot)) {
        Stop-Process -Id $Process.Id -Force
    }
    Start-Sleep -Milliseconds 500
    $Remaining = @(Get-InstalledApplicationProcesses $InstallRoot)
    if ($Remaining.Count -gt 0) {
        throw "Installed application processes did not stop: $(($Remaining.Id) -join ', ')"
    }
}

function Read-EffectiveConfiguration([string]$Executable) {
    $Text = & $Executable --config $ConfigPath show-config --ascii | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot read working configuration with: $Executable"
    }
    try {
        $Report = $Text | ConvertFrom-Json
    } catch {
        throw "Executable returned invalid show-config JSON: $($_.Exception.Message)"
    }
    if (-not $Report.config_loaded) {
        throw "Executable did not load the working config: $ConfigPath"
    }
    if (@($Report.overridden_by_environment).Count -gt 0) {
        throw "Environment variables override working config: $(@($Report.overridden_by_environment) -join ', ')"
    }
    return $Report
}

function Assert-ServiceXml([string]$XmlPath, [string]$InstallRoot) {
    try {
        [xml]$Xml = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
    } catch {
        throw "Cannot parse installed WinSW XML: $XmlPath. $($_.Exception.Message)"
    }
    $ExpectedExe = [IO.Path]::GetFullPath((Join-Path $InstallRoot "app\aerotech-docflow.exe")).TrimEnd('\')
    $ActualExe = [IO.Path]::GetFullPath([string]$Xml.service.executable).TrimEnd('\')
    $ExpectedWorkingDirectory = [IO.Path]::GetFullPath((Join-Path $InstallRoot "app")).TrimEnd('\')
    $ActualWorkingDirectory = [IO.Path]::GetFullPath([string]$Xml.service.workingdirectory).TrimEnd('\')
    $ExpectedArguments = '--config "' + [IO.Path]::GetFullPath($ConfigPath).TrimEnd('\') + '" run'
    if ([string]$Xml.service.id -ne $ServiceName -or
        -not $ActualExe.Equals($ExpectedExe, [StringComparison]::OrdinalIgnoreCase) -or
        -not $ActualWorkingDirectory.Equals($ExpectedWorkingDirectory, [StringComparison]::OrdinalIgnoreCase) -or
        [string]$Xml.service.arguments -ne $ExpectedArguments) {
        throw "Installed WinSW XML does not match the canonical installation and working config: $XmlPath"
    }
}

function Start-InstalledRuntime([string]$InstallRoot, [bool]$ServiceInstalled) {
    $Executable = Join-Path $InstallRoot "app\aerotech-docflow.exe"
    if ($ServiceInstalled) {
        $Service = Get-Service -Name $ServiceName
        if ($Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
            Start-Service -Name $ServiceName
        }
        $Service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
    } else {
        if (@(Get-InstalledApplicationProcesses $InstallRoot).Count -eq 0) {
            $Arguments = @('--config', ('"' + $ConfigPath + '"'), 'run')
            Start-Process `
                -FilePath $Executable `
                -ArgumentList $Arguments `
                -WorkingDirectory (Join-Path $InstallRoot "app") `
                -WindowStyle Hidden | Out-Null
        }
    }
}

function Wait-LocalHealth([string]$Executable, [int]$TimeoutSeconds = 45) {
    $ConfigReport = Read-EffectiveConfiguration $Executable
    $HostName = [string]$ConfigReport.effective_environment.DOCFLOW_HOST
    $Port = [int]$ConfigReport.effective_environment.DOCFLOW_PORT
    if ($HostName -notin @('127.0.0.1', 'localhost')) {
        throw "Health check is restricted to localhost; configured host: $HostName"
    }
    $HealthUri = "http://${HostName}:$Port/health"
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $LastError = "no response"
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Request = [Net.HttpWebRequest][Net.WebRequest]::Create($HealthUri)
            $Request.Method = 'GET'
            $Request.Proxy = $null
            $Request.Timeout = 2000
            $Request.ReadWriteTimeout = 2000
            $Response = $Request.GetResponse()
            try {
                $Reader = New-Object IO.StreamReader($Response.GetResponseStream())
                try {
                    $Payload = $Reader.ReadToEnd() | ConvertFrom-Json
                } finally {
                    $Reader.Dispose()
                }
            } finally {
                $Response.Dispose()
            }
            if ($Payload.status -eq 'ok') {
                Write-Host "Health check passed: $HealthUri"
                return
            }
            $LastError = "unexpected payload"
        } catch {
            $LastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 1
    }
    throw "Local health check did not pass within $TimeoutSeconds seconds: $HealthUri; last error: $LastError"
}

function Start-AndVerifyRuntime([string]$InstallRoot, [bool]$ServiceInstalled) {
    $Executable = Join-Path $InstallRoot "app\aerotech-docflow.exe"
    & $Executable --config $ConfigPath preflight
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight failed with exit code $LASTEXITCODE."
    }
    Start-InstalledRuntime $InstallRoot $ServiceInstalled
    Wait-LocalHealth $Executable
}

function Remove-TemporaryUpdateDirectory([string]$Directory) {
    $ResolvedTempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $ResolvedDirectory = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    if (-not $ResolvedDirectory.StartsWith(
        $ResolvedTempBase + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    ) -or -not (Split-Path -Leaf $ResolvedDirectory).StartsWith('AerotechDocflow-update-')) {
        throw "Refusing to remove unexpected temporary directory: $ResolvedDirectory"
    }
    Set-Location $env:SystemRoot
    if (Test-Path -LiteralPath $ResolvedDirectory) {
        Remove-Item -LiteralPath $ResolvedDirectory -Recurse -Force
    }
}

function Invoke-UpdateTransaction {
Assert-Administrator
$InstallDir = Get-CanonicalDocflowInstallDirectory
$InstallDir = Assert-CanonicalDocflowInstallDirectory $InstallDir
Assert-NoLegacyX86DocflowInstallation
$RollbackDir = "$InstallDir.rollback"
$InstallDir = Assert-SafeManagedDirectory $InstallDir (Get-CanonicalDocflowInstallDirectory)
$RollbackDir = Assert-SafeManagedDirectory $RollbackDir ((Get-CanonicalDocflowInstallDirectory) + '.rollback')
$ResolvedPackage = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
$ResolvedTemp = [IO.Path]::GetFullPath($TempRoot).TrimEnd('\')
if (-not (Test-IsSameOrChildPath $ResolvedPackage $ResolvedTemp)) {
    throw "Downloaded package is outside its unique temporary directory."
}
foreach ($Required in @(
    $ConfigPath,
    (Join-Path $InstallDir "app\aerotech-docflow.exe"),
    (Join-Path $ResolvedPackage "app\aerotech-docflow.exe"),
    (Join-Path $ResolvedPackage "update.ps1"),
    (Join-Path $ResolvedPackage "update-helper.ps1"),
    (Join-Path $ResolvedPackage "common_paths.ps1")
)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Required update file not found: $Required"
    }
}
Assert-DocflowPackageManifest $ResolvedPackage

$ResolvedReadyFile = [IO.Path]::GetFullPath($ReadyFile)
$ExpectedReadyFile = Join-Path $ResolvedTemp "helper.ready"
if (-not $ResolvedReadyFile.Equals($ExpectedReadyFile, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected helper handshake path: $ResolvedReadyFile"
}
Set-Content -LiteralPath $ResolvedReadyFile -Value ([string]$PID) -Encoding ASCII

try {
    $Parent = Get-Process -Id $ParentProcessId -ErrorAction Stop
    $Parent.WaitForExit(60 * 1000)
} catch {
    if (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue) {
        throw "Bootstrap updater did not exit within 60 seconds: PID=$ParentProcessId"
    }
}

$OldMoved = $false
$ServiceInstalled = [bool](Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
$OldExecutable = Join-Path $InstallDir "app\aerotech-docflow.exe"
$OldConfig = Read-EffectiveConfiguration $OldExecutable
$Incoming = [string]$OldConfig.effective_environment.SCANNER_INCOMING_DIR
if ([string]::IsNullOrWhiteSpace($Incoming)) {
    throw "scanner.incoming_dir is empty in the working config."
}
$ScannerLock = Join-Path (Get-NormalizedFullPath $Incoming) ".scanner.lock"
$OldServiceXml = Join-Path $InstallDir "service\docflow-service.xml"
if ($ServiceInstalled) {
    $NewWrapper = Join-Path $ResolvedPackage "service\docflow-service.exe"
    foreach ($Required in @($OldServiceXml, $NewWrapper)) {
        if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
            throw "Service update file not found: $Required"
        }
    }
    Assert-ServiceXml $OldServiceXml $InstallDir
}

$UpdateError = $null
$RollbackError = $null
$ShutdownStarted = $false
$OldVersionVerified = $false
try {
    Assert-NoScannerActivity $ScannerLock
    $ShutdownStarted = $true
    Stop-InstalledRuntime $InstallDir
    Assert-NoScannerActivity $ScannerLock

    # No history is retained. A leftover fixed rollback must be removed before
    # the current installation can be renamed to the single rollback path.
    Remove-PreviousUpdateDirectories $InstallDir

    Move-Item -LiteralPath $InstallDir -Destination $RollbackDir
    $OldMoved = $true
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
    foreach ($Item in Get-ChildItem -LiteralPath $ResolvedPackage -Force) {
        Copy-Item -LiteralPath $Item.FullName -Destination $InstallDir -Recurse -Force
    }
    Assert-DocflowPackageManifest $InstallDir

    if ($ServiceInstalled) {
        $SavedServiceXml = Join-Path $RollbackDir "service\docflow-service.xml"
        $InstalledServiceXml = Join-Path $InstallDir "service\docflow-service.xml"
        Assert-ServiceXml $SavedServiceXml $InstallDir
        Copy-Item -LiteralPath $SavedServiceXml -Destination $InstalledServiceXml
        Assert-ServiceXml $InstalledServiceXml $InstallDir
    }

    Start-AndVerifyRuntime $InstallDir $ServiceInstalled
    Remove-SafeManagedDirectory $RollbackDir ((Get-CanonicalDocflowInstallDirectory) + '.rollback')
    Write-Host "UPDATE SUCCEEDED"
    Write-Host "Active installation: $InstallDir"
    Write-Host "Rollback history was removed. ProgramData and archive data were not changed."
} catch {
    $UpdateError = $_
    if ($ShutdownStarted) {
        try {
            Stop-InstalledRuntime $InstallDir
            if ($OldMoved) {
                Remove-SafeManagedDirectory $InstallDir (Get-CanonicalDocflowInstallDirectory)
                Move-Item -LiteralPath $RollbackDir -Destination $InstallDir
            }
            if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
                throw "Canonical installation directory is missing after rollback."
            }
            Start-AndVerifyRuntime $InstallDir $ServiceInstalled
            $OldVersionVerified = $true
            if (Test-Path -LiteralPath $RollbackDir) {
                Remove-SafeManagedDirectory $RollbackDir ((Get-CanonicalDocflowInstallDirectory) + '.rollback')
            }
            Write-Host "UPDATE FAILED; OLD VERSION RESTORED"
            Write-Host "Reason: $($UpdateError.Exception.Message)"
        } catch {
            $RollbackError = $_
        }
    }
}

if ($RollbackError) {
    throw (
        "UPDATE AND AUTOMATIC ROLLBACK FAILED. " +
        "Update error: $($UpdateError.Exception.Message) " +
        "Rollback error: $($RollbackError.Exception.Message) " +
        "Do not send scan requests until the installation is repaired."
    )
}
if ($UpdateError) {
    if ($OldVersionVerified) {
        throw "Update failed; the old version was restored and passed health check: $($UpdateError.Exception.Message)"
    }
    throw "Update was refused before the installed runtime was stopped: $($UpdateError.Exception.Message)"
}
}

try {
    Invoke-UpdateTransaction
} finally {
    try {
        Remove-TemporaryUpdateDirectory $TempRoot
    } catch {
        Write-Warning "Could not remove temporary update directory: $TempRoot; $($_.Exception.Message)"
    }
}
