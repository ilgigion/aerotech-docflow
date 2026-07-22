param(
    [string]$InstallDir = "$env:ProgramFiles\Aerotech Docflow",
    [string]$ConfigPath = "$env:ProgramData\Aerotech Docflow\config\config.toml",
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"
$ServiceName = "AerotechDocflow"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

function Get-FullPath([string]$Path) {
    $FullPath = [IO.Path]::GetFullPath($Path)
    $PathRoot = [IO.Path]::GetPathRoot($FullPath)
    if ($FullPath.Equals($PathRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $PathRoot
    }
    return $FullPath.TrimEnd('\')
}

function Test-IsSameOrChildPath([string]$Candidate, [string]$Parent) {
    $FullCandidate = Get-FullPath $Candidate
    $FullParent = Get-FullPath $Parent
    if ($FullCandidate.Equals($FullParent, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $ParentPrefix = $FullParent
    if (-not $ParentPrefix.EndsWith([string][IO.Path]::DirectorySeparatorChar)) {
        $ParentPrefix += [IO.Path]::DirectorySeparatorChar
    }
    return $FullCandidate.StartsWith(
        $ParentPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-Administrator {
    $Principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run update_current_machine.ps1 from PowerShell opened with Run as administrator."
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

function Get-InstalledApplicationProcesses([string]$ApplicationRoot) {
    $Matches = @()
    foreach ($Process in @(Get-Process -Name "aerotech-docflow" -ErrorAction SilentlyContinue)) {
        try {
            $ExecutablePath = [string]$Process.Path
        } catch {
            throw "Cannot determine executable path for aerotech-docflow PID=$($Process.Id). Update refused."
        }
        if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
            throw "Cannot determine executable path for aerotech-docflow PID=$($Process.Id). Update refused."
        }
        if (Test-IsSameOrChildPath $ExecutablePath $ApplicationRoot) {
            $Matches += $Process
        }
    }
    return @($Matches)
}

function Stop-InstalledApplication([string]$ApplicationRoot) {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($Service -and $Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Write-Host "Stopping service $ServiceName..."
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $Service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
        $Service.Refresh()
        if ($Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            throw "Service $ServiceName did not stop within 30 seconds."
        }
    }

    $Processes = @(Get-InstalledApplicationProcesses $ApplicationRoot)
    foreach ($Process in $Processes) {
        Write-Host "Stopping application PID=$($Process.Id)..."
        Stop-Process -Id $Process.Id -Force -ErrorAction Stop
    }
    if ($Processes.Count -gt 0) {
        Start-Sleep -Milliseconds 500
    }
    $Remaining = @(Get-InstalledApplicationProcesses $ApplicationRoot)
    if ($Remaining.Count -gt 0) {
        $Pids = ($Remaining | ForEach-Object { $_.Id }) -join ", "
        throw "Installed application is still running. PID: $Pids"
    }
}

function Assert-PackageManifest([string]$Root) {
    $ManifestPath = Join-Path $Root "build-manifest.json"
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "New package manifest not found: $ManifestPath"
    }
    try {
        $ParsedManifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $Entries = @($ParsedManifest)
    } catch {
        throw "Cannot read new package manifest: $ManifestPath. $($_.Exception.Message)"
    }
    if ($Entries.Count -eq 0) {
        throw "New package manifest is empty: $ManifestPath"
    }

    $RootPrefix = Get-FullPath $Root
    if (-not $RootPrefix.EndsWith([string][IO.Path]::DirectorySeparatorChar)) {
        $RootPrefix += [IO.Path]::DirectorySeparatorChar
    }
    $ManifestPaths = @{}
    foreach ($Entry in $Entries) {
        $RelativePath = [string]$Entry.Path
        if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) {
            throw "Unsafe path in package manifest: $RelativePath"
        }
        $FilePath = [IO.Path]::GetFullPath((Join-Path $Root $RelativePath))
        if (-not $FilePath.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Path escapes package directory in manifest: $RelativePath"
        }
        $ManifestKey = $RelativePath.Replace('/', '\').ToLowerInvariant()
        if ($ManifestPaths.ContainsKey($ManifestKey)) {
            throw "Duplicate path in package manifest: $RelativePath"
        }
        $ManifestPaths[$ManifestKey] = $true
        if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
            throw "Package file listed in manifest is missing: $RelativePath"
        }
        $File = Get-Item -LiteralPath $FilePath
        if ($File.Length -ne [Int64]$Entry.Size) {
            throw "Package file size does not match manifest: $RelativePath"
        }
        $ActualHash = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash
        if ($ActualHash -ne [string]$Entry.SHA256) {
            throw "Package file SHA-256 does not match manifest: $RelativePath"
        }
    }

    foreach ($ActualFile in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
        $ActualRelative = $ActualFile.FullName.Substring($RootPrefix.Length)
        if ($ActualRelative.Equals("build-manifest.json", [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $ActualKey = $ActualRelative.Replace('/', '\').ToLowerInvariant()
        if (-not $ManifestPaths.ContainsKey($ActualKey)) {
            throw "Package contains a file not listed in the manifest: $ActualRelative"
        }
    }
}

function Assert-ServiceXml([string]$XmlPath, [string]$ApplicationRoot, [string]$WorkingConfig) {
    try {
        [xml]$Xml = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
    } catch {
        throw "Cannot parse the installed WinSW XML: $XmlPath. $($_.Exception.Message)"
    }
    $ExpectedExe = Get-FullPath (Join-Path $ApplicationRoot "app\aerotech-docflow.exe")
    $ActualExe = Get-FullPath ([string]$Xml.service.executable)
    $ExpectedWorkingDirectory = Get-FullPath (Join-Path $ApplicationRoot "app")
    $ActualWorkingDirectory = Get-FullPath ([string]$Xml.service.workingdirectory)
    $ExpectedArguments = '--config "' + (Get-FullPath $WorkingConfig) + '" run'

    if ([string]$Xml.service.id -ne $ServiceName -or
        -not $ActualExe.Equals($ExpectedExe, [StringComparison]::OrdinalIgnoreCase) -or
        -not $ActualWorkingDirectory.Equals($ExpectedWorkingDirectory, [StringComparison]::OrdinalIgnoreCase) -or
        [string]$Xml.service.arguments -ne $ExpectedArguments) {
        throw "Installed WinSW XML does not match this installation or working config: $XmlPath"
    }
}

Assert-Administrator

if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $SourceDir = $PSScriptRoot
}
$ResolvedSource = Get-FullPath $SourceDir
$ResolvedInstall = Get-FullPath $InstallDir
$ResolvedConfig = Get-FullPath $ConfigPath
$InstallParent = Split-Path -Parent $ResolvedInstall
$InstallName = Split-Path -Leaf $ResolvedInstall
$RollbackDir = Join-Path $InstallParent "$InstallName.rollback-$Timestamp"
$FailedUpdateDir = Join-Path $InstallParent "$InstallName.failed-update-$Timestamp"
$ConfigBackup = "$ResolvedConfig.before-update-$Timestamp.bak"
$OldExe = Join-Path $ResolvedInstall "app\aerotech-docflow.exe"
$NewSourceExe = Join-Path $ResolvedSource "app\aerotech-docflow.exe"
$OldServiceXml = Join-Path $ResolvedInstall "service\docflow-service.xml"
$NewSourceWrapper = Join-Path $ResolvedSource "service\docflow-service.exe"

foreach ($RequiredFile in @($OldExe, $NewSourceExe, $ResolvedConfig)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required file not found: $RequiredFile"
    }
}
if (Test-IsSameOrChildPath $ResolvedSource $ResolvedInstall) {
    throw "The new package must be outside the current installation directory: $ResolvedSource"
}
if (Test-IsSameOrChildPath $ResolvedConfig $ResolvedInstall) {
    throw "The working config must be outside the application directory: $ResolvedConfig"
}
foreach ($ReservedPath in @($RollbackDir, $FailedUpdateDir, $ConfigBackup)) {
    if (Test-Path -LiteralPath $ReservedPath) {
        throw "Timestamped update path already exists; wait one second and retry: $ReservedPath"
    }
}

Assert-PackageManifest $ResolvedSource

$ConfigReportText = & $OldExe --config $ResolvedConfig show-config --ascii | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Cannot read the working configuration with the installed executable: $ResolvedConfig"
}
try {
    $ConfigReport = $ConfigReportText | ConvertFrom-Json
} catch {
    throw "Installed executable returned invalid show-config JSON. $($_.Exception.Message)"
}
if (-not $ConfigReport.config_loaded) {
    throw "Installed executable did not load the working config: $ResolvedConfig"
}
if (@($ConfigReport.overridden_by_environment).Count -gt 0) {
    throw (
        "Update refused because environment variables override the working config: " +
        (@($ConfigReport.overridden_by_environment) -join ", ")
    )
}
$IncomingDir = [string]$ConfigReport.effective_environment.SCANNER_INCOMING_DIR
if ([string]::IsNullOrWhiteSpace($IncomingDir)) {
    throw "scanner.incoming_dir is empty in the working config."
}
$ScannerLock = Join-Path (Get-FullPath $IncomingDir) ".scanner.lock"

$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {
    foreach ($RequiredServiceFile in @($OldServiceXml, $NewSourceWrapper)) {
        if (-not (Test-Path -LiteralPath $RequiredServiceFile -PathType Leaf)) {
            throw "Service update file not found: $RequiredServiceFile"
        }
    }
    Assert-ServiceXml $OldServiceXml $ResolvedInstall $ResolvedConfig
}

# Refuse before stopping anything if a scan may be in progress. Repeat the
# checks after shutdown to close the race with a request that was just starting.
Assert-NoScannerActivity $ScannerLock
Stop-InstalledApplication $ResolvedInstall
Assert-NoScannerActivity $ScannerLock

$ServiceAfterStop = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ServiceAfterStop -and $ServiceAfterStop.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
    throw "Service $ServiceName is not stopped. Update refused."
}

Copy-Item -LiteralPath $ResolvedConfig -Destination $ConfigBackup
$OriginalConfigHash = (Get-FileHash -LiteralPath $ResolvedConfig -Algorithm SHA256).Hash
$BackupConfigHash = (Get-FileHash -LiteralPath $ConfigBackup -Algorithm SHA256).Hash
if ($OriginalConfigHash -ne $BackupConfigHash) {
    Remove-Item -LiteralPath $ConfigBackup -Force -ErrorAction SilentlyContinue
    throw "Working config backup verification failed: $ConfigBackup"
}

$OldInstallationMoved = $false
try {
    Write-Host "Moving current installation to: $RollbackDir"
    Move-Item -LiteralPath $ResolvedInstall -Destination $RollbackDir
    $OldInstallationMoved = $true

    New-Item -ItemType Directory -Path $ResolvedInstall | Out-Null
    foreach ($Item in Get-ChildItem -LiteralPath $ResolvedSource -Force) {
        Copy-Item -LiteralPath $Item.FullName -Destination $ResolvedInstall -Recurse -Force
    }
    Assert-PackageManifest $ResolvedInstall

    if ($ExistingService) {
        $SavedServiceXml = Join-Path $RollbackDir "service\docflow-service.xml"
        $InstalledServiceXml = Join-Path $ResolvedInstall "service\docflow-service.xml"
        Assert-ServiceXml $SavedServiceXml $ResolvedInstall $ResolvedConfig
        Copy-Item -LiteralPath $SavedServiceXml -Destination $InstalledServiceXml
        Assert-ServiceXml $InstalledServiceXml $ResolvedInstall $ResolvedConfig
    }

    $NewInstalledExe = Join-Path $ResolvedInstall "app\aerotech-docflow.exe"
    Write-Host "Running preflight with the new executable..."
    & $NewInstalledExe --config $ResolvedConfig preflight
    if ($LASTEXITCODE -ne 0) {
        throw "New executable preflight failed with exit code $LASTEXITCODE."
    }
} catch {
    $UpdateFailure = $_
    $RollbackFailure = $null
    if ($OldInstallationMoved) {
        try {
            if (Test-Path -LiteralPath $ResolvedInstall) {
                Move-Item -LiteralPath $ResolvedInstall -Destination $FailedUpdateDir
            }
            Move-Item -LiteralPath $RollbackDir -Destination $ResolvedInstall
            if (-not (Test-Path -LiteralPath $OldExe -PathType Leaf)) {
                throw "Restored executable is missing: $OldExe"
            }
        } catch {
            $RollbackFailure = $_
        }
    }

    if ($RollbackFailure) {
        throw (
            "UPDATE FAILED AND AUTOMATIC ROLLBACK FAILED. " +
            "Update error: $($UpdateFailure.Exception.Message) " +
            "Rollback error: $($RollbackFailure.Exception.Message) " +
            "Do not start the service. Inspect: $ResolvedInstall and $RollbackDir"
        )
    }
    throw (
        "UPDATE FAILED. The old application directory was restored and remains stopped. " +
        "Error: $($UpdateFailure.Exception.Message) " +
        "Rejected new files, if any, are preserved at: $FailedUpdateDir"
    )
}

Write-Host "UPDATE FILES READY"
Write-Host "The new application and the Windows service remain stopped."
Write-Host "Application: $ResolvedInstall"
Write-Host "Working config (unchanged): $ResolvedConfig"
Write-Host "Config backup: $ConfigBackup"
Write-Host "Rollback directory: $RollbackDir"
Write-Host "ProgramData, incoming data and archive files were not copied or replaced."
