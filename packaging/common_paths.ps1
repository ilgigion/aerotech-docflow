function Get-CanonicalProgramFilesDirectory {
    if ([Environment]::Is64BitOperatingSystem) {
        # Windows exposes ProgramW6432 to both 32-bit and 64-bit processes.
        # Unlike the process-specific ProgramFiles variable, it never redirects an x86 PowerShell process
        # to "Program Files (x86)".
        $ProgramFilesDirectory = [Environment]::GetEnvironmentVariable(
            "ProgramW6432",
            [EnvironmentVariableTarget]::Process
        )
        if ([string]::IsNullOrWhiteSpace($ProgramFilesDirectory)) {
            throw "ProgramW6432 is missing on 64-bit Windows. Installation is refused to prevent x86 redirection."
        }
    } else {
        $ProgramFilesDirectory = [Environment]::GetEnvironmentVariable(
            "ProgramFiles",
            [EnvironmentVariableTarget]::Process
        )
    }

    if ([string]::IsNullOrWhiteSpace($ProgramFilesDirectory)) {
        throw "Cannot determine the native Program Files directory."
    }
    $Resolved = [IO.Path]::GetFullPath($ProgramFilesDirectory).TrimEnd('\')
    if ([Environment]::Is64BitOperatingSystem -and
        (Split-Path -Leaf $Resolved).Equals("Program Files (x86)", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Native Program Files unexpectedly resolves to Program Files (x86). Installation is refused."
    }
    return $Resolved
}

function Get-CanonicalDocflowInstallDirectory {
    return Join-Path (Get-CanonicalProgramFilesDirectory) "Aerotech Docflow"
}

function Assert-CanonicalDocflowInstallDirectory([string]$InstallDir) {
    $Canonical = [IO.Path]::GetFullPath((Get-CanonicalDocflowInstallDirectory)).TrimEnd('\')
    $Requested = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    if (-not $Requested.Equals($Canonical, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Non-canonical installation path is forbidden. Expected: $Canonical; received: $Requested"
    }
    return $Canonical
}

function Assert-NoLegacyX86DocflowInstallation {
    if (-not [Environment]::Is64BitOperatingSystem) {
        return
    }
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable(
        "ProgramFiles(x86)",
        [EnvironmentVariableTarget]::Process
    )
    if ([string]::IsNullOrWhiteSpace($ProgramFilesX86)) {
        return
    }
    $Legacy = Join-Path ([IO.Path]::GetFullPath($ProgramFilesX86).TrimEnd('\')) "Aerotech Docflow"
    $Canonical = Get-CanonicalDocflowInstallDirectory
    if (-not $Legacy.Equals($Canonical, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $Legacy -PathType Container) -and
        (Get-ChildItem -LiteralPath $Legacy -Force | Select-Object -First 1)) {
        throw (
            "A legacy installation exists in Program Files (x86): $Legacy. " +
            "Automatic installation/update is refused to prevent two installations. " +
            "Back it up and remove or migrate it explicitly first."
        )
    }
}

function Assert-DocflowPackageManifest([string]$PackageRoot) {
    $ResolvedRoot = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
    $ManifestPath = Join-Path $ResolvedRoot "build-manifest.json"
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Package manifest not found: $ManifestPath"
    }

    try {
        $ParsedManifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $Entries = @($ParsedManifest)
    } catch {
        throw "Cannot read package manifest: $ManifestPath. $($_.Exception.Message)"
    }
    if ($Entries.Count -eq 0) {
        throw "Package manifest is empty: $ManifestPath"
    }

    $RootPrefix = $ResolvedRoot + [IO.Path]::DirectorySeparatorChar
    $ManifestPaths = @{}
    foreach ($Entry in $Entries) {
        $RelativePath = [string]$Entry.Path
        if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) {
            throw "Unsafe path in package manifest: $RelativePath"
        }
        $FilePath = [IO.Path]::GetFullPath((Join-Path $ResolvedRoot $RelativePath))
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

    foreach ($ActualFile in Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -Force -File) {
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
