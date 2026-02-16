param(
    [Parameter(Mandatory = $true)]
    [string]$BaselineRoot,

    [Parameter(Mandatory = $true)]
    [string]$CandidateRoot,

    [string]$ReportPath,

    [switch]$AllowDifferences
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-DirectoryPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Path '$Path' is not a directory."
    }

    return [string]$resolved
}

function Get-FileMap {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $rootPath = [string](Resolve-Path -LiteralPath $Root)
    $rootFull = [System.IO.Path]::GetFullPath($rootPath).TrimEnd([char[]]@('\', '/'))
    $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    $files = Get-ChildItem -LiteralPath $rootPath -Recurse -File
    $map = @{}

    foreach ($file in $files) {
        $fullName = [System.IO.Path]::GetFullPath($file.FullName)
        if ($fullName.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $relative = $fullName.Substring($rootPrefix.Length)
        } else {
            $relative = $file.Name
        }
        $normalized = $relative.Replace("\", "/")
        $map[$normalized] = $file.FullName
    }

    return $map
}

function Is-BinaryBytes {
    param(
        [byte[]]$Bytes
    )

    if ($Bytes.Length -eq 0) {
        return $false
    }

    return $Bytes -contains 0
}

function Get-NormalizedContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    $fullPath = [System.IO.Path]::GetFullPath($FilePath)
    if ($fullPath.StartsWith("\\?\")) {
        $readPath = $fullPath
    } elseif ($fullPath.StartsWith("\\")) {
        $readPath = "\\?\UNC\" + $fullPath.TrimStart("\")
    } else {
        $readPath = "\\?\" + $fullPath
    }

    $bytes = [System.IO.File]::ReadAllBytes($readPath)
    if (Is-BinaryBytes -Bytes $bytes) {
        return @{
            type = "binary"
            value = [System.Convert]::ToBase64String($bytes)
        }
    }

    $utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $text = $utf8Strict.GetString($bytes)
    } catch [System.Text.DecoderFallbackException] {
        $text = [System.Text.Encoding]::Default.GetString($bytes)
    }

    # Text-exact parity normalization: EOL normalization + ignore trailing EOF whitespace.
    $text = $text -replace "`r`n", "`n"
    $text = $text -replace "`r", "`n"
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "\s+\z", "")

    return @{
        type = "text"
        value = $text
    }
}

$baselinePath = Resolve-DirectoryPath -Path $BaselineRoot
$candidatePath = Resolve-DirectoryPath -Path $CandidateRoot

$baselineFiles = Get-FileMap -Root $baselinePath
$candidateFiles = Get-FileMap -Root $candidatePath

$added = @($candidateFiles.Keys | Where-Object { -not $baselineFiles.ContainsKey($_) } | Sort-Object)
$removed = @($baselineFiles.Keys | Where-Object { -not $candidateFiles.ContainsKey($_) } | Sort-Object)
$common = @($baselineFiles.Keys | Where-Object { $candidateFiles.ContainsKey($_) } | Sort-Object)

$changed = New-Object System.Collections.Generic.List[object]

foreach ($relativePath in $common) {
    $baselineContent = $null
    $candidateContent = $null
    $baselineError = $null
    $candidateError = $null

    try {
        $baselineContent = Get-NormalizedContent -FilePath $baselineFiles[$relativePath]
    } catch {
        $baselineError = $_.Exception.GetType().Name + ": " + $_.Exception.Message
    }

    try {
        $candidateContent = Get-NormalizedContent -FilePath $candidateFiles[$relativePath]
    } catch {
        $candidateError = $_.Exception.GetType().Name + ": " + $_.Exception.Message
    }

    if ($baselineError -or $candidateError) {
        if ($baselineError -and $candidateError -and $baselineError -eq $candidateError) {
            continue
        }

        $changed.Add(@{
                path = $relativePath
                reason = "read_error"
                baseline_type = if ($baselineContent) { $baselineContent.type } else { "error" }
                candidate_type = if ($candidateContent) { $candidateContent.type } else { "error" }
                baseline_error = $baselineError
                candidate_error = $candidateError
            })
        continue
    }

    if ($baselineContent.type -ne $candidateContent.type) {
        $changed.Add(@{
                path = $relativePath
                reason = "type_changed"
                baseline_type = $baselineContent.type
                candidate_type = $candidateContent.type
            })
        continue
    }

    if ($baselineContent.value -ne $candidateContent.value) {
        $changed.Add(@{
                path = $relativePath
                reason = if ($baselineContent.type -eq "binary") { "binary_diff" } else { "text_diff" }
                baseline_type = $baselineContent.type
                candidate_type = $candidateContent.type
            })
    }
}

$report = [pscustomobject]@{
    baseline_root = $baselinePath
    candidate_root = $candidatePath
    totals = [pscustomobject]@{
        baseline_files = $baselineFiles.Count
        candidate_files = $candidateFiles.Count
        added = $added.Count
        removed = $removed.Count
        changed = $changed.Count
    }
    added = [string[]]$added
    removed = [string[]]$removed
    changed = $changed.ToArray()
}

if ($ReportPath) {
    $reportDir = Split-Path -Parent $ReportPath
    if ($reportDir -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    $json = $report | ConvertTo-Json -Depth 8
    Set-Content -LiteralPath $ReportPath -Value $json -Encoding UTF8
}

Write-Output "Parity summary:"
Write-Output ("- Baseline files : {0}" -f $report.totals.baseline_files)
Write-Output ("- Candidate files: {0}" -f $report.totals.candidate_files)
Write-Output ("- Added          : {0}" -f $report.totals.added)
Write-Output ("- Removed        : {0}" -f $report.totals.removed)
Write-Output ("- Changed        : {0}" -f $report.totals.changed)

if ($added.Count -gt 0) {
    Write-Output ""
    Write-Output "Added files:"
    $added | ForEach-Object { Write-Output ("  + {0}" -f $_) }
}

if ($removed.Count -gt 0) {
    Write-Output ""
    Write-Output "Removed files:"
    $removed | ForEach-Object { Write-Output ("  - {0}" -f $_) }
}

if ($changed.Count -gt 0) {
    Write-Output ""
    Write-Output "Changed files:"
    foreach ($entry in $changed) {
        Write-Output ("  * {0} ({1})" -f $entry.path, $entry.reason)
    }
}

$hasDifferences = ($added.Count + $removed.Count + $changed.Count) -gt 0
if ($hasDifferences -and -not $AllowDifferences) {
    exit 1
}

exit 0
