param(
    [string]$Url = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "common_paths.ps1")

function Assert-Administrator {
    $Principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run update.ps1 from PowerShell opened with Run as administrator."
    }
}

function Expand-ZipSafely([string]$ZipPath, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $ResolvedDestination = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    $DestinationPrefix = $ResolvedDestination + [IO.Path]::DirectorySeparatorChar
    New-Item -ItemType Directory -Path $ResolvedDestination | Out-Null

    $Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        if ($Archive.Entries.Count -gt 100000) {
            throw "Release archive contains too many entries."
        }
        [Int64]$ExpandedBytes = 0
        foreach ($Entry in $Archive.Entries) {
            $EntryName = [string]$Entry.FullName
            if ([string]::IsNullOrWhiteSpace($EntryName)) {
                continue
            }
            $UnixFileType = (($Entry.ExternalAttributes -shr 16) -band 0xF000)
            $HasWindowsReparseAttribute = (
                $Entry.ExternalAttributes -band [int][IO.FileAttributes]::ReparsePoint
            ) -ne 0
            if ($UnixFileType -eq 0xA000 -or $HasWindowsReparseAttribute) {
                throw "Symbolic links are forbidden in release archive: $EntryName"
            }
            $NormalizedEntryName = $EntryName.Replace('\', '/')
            $UnsafeSegments = @(
                $NormalizedEntryName.Split('/') |
                    Where-Object {
                        $_ -eq '.' -or $_ -eq '..' -or $_.Contains(':') -or
                        ($_.Length -gt 0 -and ($_.EndsWith('.') -or $_.EndsWith(' ')))
                    }
            )
            if ($UnsafeSegments.Count -gt 0) {
                throw "Unsafe path segment in release archive: $EntryName"
            }
            if ([IO.Path]::IsPathRooted($EntryName) -or $EntryName.StartsWith('/') -or $EntryName.StartsWith('\')) {
                throw "Absolute path is forbidden in release archive: $EntryName"
            }
            $OutputPath = [IO.Path]::GetFullPath((Join-Path $ResolvedDestination $EntryName))
            if (-not $OutputPath.StartsWith($DestinationPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Path escapes release extraction directory: $EntryName"
            }
            $IsDirectory = $EntryName.EndsWith('/') -or $EntryName.EndsWith('\')
            if ($IsDirectory) {
                New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
                continue
            }

            $ExpandedBytes += [Int64]$Entry.Length
            if ($ExpandedBytes -gt 2GB) {
                throw "Release archive expands beyond the 2 GiB safety limit."
            }
            $OutputDirectory = Split-Path -Parent $OutputPath
            New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
            $InputStream = $Entry.Open()
            try {
                $OutputStream = New-Object IO.FileStream(
                    $OutputPath,
                    [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write,
                    [IO.FileShare]::None
                )
                try {
                    $InputStream.CopyTo($OutputStream)
                    $OutputStream.Flush()
                } finally {
                    $OutputStream.Dispose()
                }
            } finally {
                $InputStream.Dispose()
            }
        }
    } finally {
        $Archive.Dispose()
    }
}

function Get-NativePowerShellExecutable {
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        $NativePowerShell = Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe"
    } else {
        $NativePowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    }
    if (-not (Test-Path -LiteralPath $NativePowerShell -PathType Leaf)) {
        throw "Native Windows PowerShell executable not found: $NativePowerShell"
    }
    return $NativePowerShell
}

function Quote-ProcessArgument([string]$Value) {
    if ($Value.Contains('"')) {
        throw "A helper argument contains an unsupported quote character."
    }
    return '"' + $Value + '"'
}

Assert-Administrator
$CanonicalInstall = Get-CanonicalDocflowInstallDirectory
$ResolvedScriptRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
if (-not $ResolvedScriptRoot.Equals($CanonicalInstall, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Run the installed updater only from: $CanonicalInstall\update.ps1"
}
Assert-NoLegacyX86DocflowInstallation

if ([string]::IsNullOrWhiteSpace($Url) -eq [string]::IsNullOrWhiteSpace($Version)) {
    throw "Specify exactly one source: -Url <https URL to dist.zip> or -Version <GitHub release tag>."
}

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    if ($Version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "GitHub release version contains unsafe characters: $Version"
    }
    $ReleaseTag = $Version
    if ($ReleaseTag -match '^\d') {
        $ReleaseTag = "v$ReleaseTag"
    }
    $Url = "https://github.com/ilgigion/aerotech-docflow/releases/download/$ReleaseTag/dist.zip"
}

try {
    $DownloadUri = [Uri]$Url
} catch {
    throw "Invalid release URL: $Url"
}
if (-not $DownloadUri.IsAbsoluteUri -or $DownloadUri.Scheme -ne 'https') {
    throw "Only an absolute HTTPS release URL is allowed."
}
if (-not [string]::IsNullOrWhiteSpace($DownloadUri.UserInfo)) {
    throw "Credentials in the release URL are forbidden."
}

$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("AerotechDocflow-update-" + [Guid]::NewGuid().ToString('N'))
$ZipPath = Join-Path $TempRoot "dist.zip"
$ExtractRoot = Join-Path $TempRoot "extracted"
$ReadyFile = Join-Path $TempRoot "helper.ready"
$HandedOff = $false
$HelperProcess = $null
try {
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    Write-Host "Downloading release: $DownloadUri"
    $Headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and
        $DownloadUri.Host.Equals('github.com', [StringComparison]::OrdinalIgnoreCase)) {
        $Headers['Authorization'] = "Bearer $env:GITHUB_TOKEN"
    }
    Invoke-WebRequest -UseBasicParsing -Uri $DownloadUri -Headers $Headers -OutFile $ZipPath
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf) -or (Get-Item -LiteralPath $ZipPath).Length -eq 0) {
        throw "Downloaded dist.zip is empty or missing."
    }
    if ((Get-Item -LiteralPath $ZipPath).Length -gt 1GB) {
        throw "Downloaded dist.zip exceeds the 1 GiB safety limit."
    }

    Expand-ZipSafely $ZipPath $ExtractRoot
    $Candidates = @(
        Get-ChildItem -LiteralPath $ExtractRoot -Recurse -Filter "update-helper.ps1" -File |
            Where-Object {
                $Root = $_.Directory.FullName
                (Test-Path -LiteralPath (Join-Path $Root "app\aerotech-docflow.exe") -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $Root "common_paths.ps1") -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $Root "build-manifest.json") -PathType Leaf)
            }
    )
    if ($Candidates.Count -ne 1) {
        throw "Release archive must contain exactly one complete AerotechDocflow package; found: $($Candidates.Count)"
    }
    $HelperPath = $Candidates[0].FullName
    $PackageRoot = $Candidates[0].Directory.FullName
    Assert-DocflowPackageManifest $PackageRoot

    $PowerShellExe = Get-NativePowerShellExecutable
    $Arguments = @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        (Quote-ProcessArgument $HelperPath),
        '-PackageRoot',
        (Quote-ProcessArgument $PackageRoot),
        '-TempRoot',
        (Quote-ProcessArgument $TempRoot),
        '-ReadyFile',
        (Quote-ProcessArgument $ReadyFile),
        '-ParentProcessId',
        [string]$PID
    )
    $HelperProcess = Start-Process `
        -FilePath $PowerShellExe `
        -ArgumentList $Arguments `
        -WorkingDirectory $env:SystemRoot `
        -PassThru
    $HelperReady = $false
    for ($Attempt = 0; $Attempt -lt 150; $Attempt++) {
        if (Test-Path -LiteralPath $ReadyFile -PathType Leaf) {
            $HelperReady = $true
            break
        }
        if ($HelperProcess.HasExited) {
            throw "Update helper exited before completing startup handshake. Exit code: $($HelperProcess.ExitCode)"
        }
        Start-Sleep -Milliseconds 100
        $HelperProcess.Refresh()
    }
    if (-not $HelperReady) {
        throw "Update helper did not complete startup handshake within 15 seconds."
    }
    $HandedOff = $true
    Write-Host "Update helper started: PID=$($HelperProcess.Id)"
    Write-Host "This bootstrap process will now exit. The helper owns the update and rollback."
} finally {
    if (-not $HandedOff -and (Test-Path -LiteralPath $TempRoot)) {
        if ($HelperProcess -and -not $HelperProcess.HasExited) {
            Stop-Process -Id $HelperProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
