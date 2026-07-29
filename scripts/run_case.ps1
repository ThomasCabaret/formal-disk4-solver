# Keep this launcher ASCII-only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.
$ErrorActionPreference = "Stop"

function Split-CommandLine {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return @() }
    $Pattern = '(?:[^\s"]+|"[^"]*")+'
    return @([regex]::Matches($CommandLine, $Pattern) | ForEach-Object {
        $_.Value.Replace('"', '')
    })
}

function Select-IndexedValue {
    param(
        [string]$Prompt,
        [object[]]$Items,
        [scriptblock]$Formatter
    )
    for ($Index = 0; $Index -lt $Items.Count; $Index++) {
        Write-Host ("  {0}. {1}" -f ($Index + 1), (& $Formatter $Items[$Index]))
    }
    while ($true) {
        $Raw = Read-Host $Prompt
        $Selected = 0
        if ([int]::TryParse($Raw, [ref]$Selected) -and $Selected -ge 1 -and $Selected -le $Items.Count) {
            return $Items[$Selected - 1]
        }
        Write-Host "[ERROR] Enter a number between 1 and $($Items.Count)." -ForegroundColor Red
    }
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$CaseRoot = Join-Path $ProjectRoot "config\cases"
if (-not (Test-Path $CaseRoot)) {
    throw "Case directory not found: $CaseRoot"
}

$CaseEntries = @(
    Get-ChildItem -Path $CaseRoot -Directory | ForEach-Object {
        $ManifestPath = Join-Path $_.FullName "case.json"
        if (Test-Path $ManifestPath) {
            $Manifest = Get-Content -Raw -Encoding UTF8 $ManifestPath | ConvertFrom-Json
            [PSCustomObject]@{
                Id = [string]$Manifest.id
                Label = [string]$Manifest.label
                Description = [string]$Manifest.description
                Directory = $_.FullName
                Manifest = $Manifest
            }
        }
    } | Sort-Object Id
)
if ($CaseEntries.Count -eq 0) {
    throw "No case manifests were found under $CaseRoot."
}

$Tokens = Split-CommandLine $env:FORMAL_DISK4_CASE_ARGS
$RequestedCase = if ($Tokens.Count -ge 1) { $Tokens[0] } else { "" }
$RequestedMode = if ($Tokens.Count -ge 2) { $Tokens[1].ToLowerInvariant() } else { "" }
$ExtraArguments = if ($Tokens.Count -gt 2) { @($Tokens[2..($Tokens.Count - 1)]) } else { @() }

$SelectedCase = $null
if (-not [string]::IsNullOrWhiteSpace($RequestedCase)) {
    $SelectedCase = $CaseEntries | Where-Object { $_.Id -eq $RequestedCase } | Select-Object -First 1
    if (-not $SelectedCase) {
        throw "Unknown case '$RequestedCase'. Available: $($CaseEntries.Id -join ', ')"
    }
}
else {
    Write-Host "Available cases:"
    $SelectedCase = Select-IndexedValue "Choose a case" $CaseEntries { param($Item) "$($Item.Label) - $($Item.Description)" }
}

$Modes = @(
    [PSCustomObject]@{ Id = "search"; Label = "Formal search / resume" },
    [PSCustomObject]@{ Id = "pipeline"; Label = "Full pipeline: search, geometry, viewer" },
    [PSCustomObject]@{ Id = "profile"; Label = "20-second disposable profile" },
    [PSCustomObject]@{ Id = "geometry"; Label = "Geometry only" },
    [PSCustomObject]@{ Id = "visualize"; Label = "Viewer only" },
    [PSCustomObject]@{ Id = "info"; Label = "Print planar-map description" }
)
$SelectedMode = $null
if (-not [string]::IsNullOrWhiteSpace($RequestedMode)) {
    $SelectedMode = $Modes | Where-Object { $_.Id -eq $RequestedMode } | Select-Object -First 1
    if (-not $SelectedMode) {
        throw "Unknown mode '$RequestedMode'. Available: $($Modes.Id -join ', ')"
    }
}
else {
    Write-Host ""
    Write-Host "Available actions:"
    $SelectedMode = Select-IndexedValue "Choose an action" $Modes { param($Item) $Item.Label }
}

$Manifest = $SelectedCase.Manifest
$ConfigDirectory = $SelectedCase.Directory
function Resolve-CaseConfig {
    param([string]$Key)
    $Name = [string]$Manifest.configs.$Key
    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw "Case '$($SelectedCase.Id)' does not define a '$Key' configuration."
    }
    $Path = Join-Path $ConfigDirectory $Name
    if (-not (Test-Path $Path)) {
        throw "Configuration file not found: $Path"
    }
    return $Path
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run setup.bat first."
}
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"
$SourceDirectory = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrEmpty($env:PYTHONPATH)) {
    $env:PYTHONPATH = $SourceDirectory
}
else {
    $env:PYTHONPATH = "$SourceDirectory$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"
}

$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDirectory "case_$($SelectedCase.Id)_$($SelectedMode.Id)_$Timestamp.log"
$TranscriptStarted = $false
$ExitCode = 0

function Invoke-Stage {
    param(
        [string]$Title,
        [string[]]$Arguments
    )
    Write-Host ""
    Write-Host $Title
    Write-Host "[INFO] Command: $Python $($Arguments -join ' ')"
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Stage failed with exit code $LASTEXITCODE."
    }
}

try {
    try {
        Start-Transcript -Path $LogFile -Append | Out-Null
        $TranscriptStarted = $true
    }
    catch {
        Write-Warning "Could not start the transcript log: $($_.Exception.Message)"
    }

    Write-Host "============================================================"
    Write-Host "Formal Contour Solver - Case Runner"
    Write-Host "Case: $($SelectedCase.Id)"
    Write-Host "Description: $($SelectedCase.Description)"
    Write-Host "Mode: $($SelectedMode.Id)"
    Write-Host "Working directory: $ProjectRoot"
    Write-Host "Log file: $LogFile"
    Write-Host "============================================================"
    Write-Host ""
    & $Python --version
    if ($LASTEXITCODE -ne 0) { throw "Python could not be started." }

    switch ($SelectedMode.Id) {
        "search" {
            $Config = Resolve-CaseConfig "search"
            $Arguments = @("-m", "formal_disk4", "run", "--config", $Config) + $ExtraArguments
            Invoke-Stage "[SEARCH] Formal enumeration and word solving" $Arguments
        }
        "profile" {
            $Config = Resolve-CaseConfig "profile"
            $Arguments = @("-m", "formal_disk4", "run", "--config", $Config) + $ExtraArguments
            Invoke-Stage "[PROFILE] Disposable bounded run" $Arguments
        }
        "geometry" {
            $Config = Resolve-CaseConfig "geometry"
            $Arguments = @("-m", "formal_disk4", "geometry", "--config", $Config) + $ExtraArguments
            Invoke-Stage "[GEOMETRY] Single-piece realization" $Arguments
        }
        "visualize" {
            $Config = Resolve-CaseConfig "visualizer"
            $Arguments = @("-m", "formal_disk4", "visualize", "--config", $Config) + $ExtraArguments
            Invoke-Stage "[VIEWER] Mapping-derived assembly" $Arguments
        }
        "info" {
            if ($ExtraArguments.Count -gt 0) {
                throw "The info mode does not accept additional arguments."
            }
            Invoke-Stage "[INFO] Registered planar map" @("-m", "formal_disk4", "map-info", "--map", [string]$Manifest.map)
        }
        "pipeline" {
            $Unknown = @($ExtraArguments | Where-Object { $_ -notin @("--restart", "--no-resume") })
            if ($Unknown.Count -gt 0) {
                throw "Full pipeline accepts only --restart and --no-resume. Unsupported: $($Unknown -join ' ')"
            }
            $SearchConfig = Resolve-CaseConfig "search"
            $GeometryConfig = Resolve-CaseConfig "geometry"
            $VisualizerConfig = Resolve-CaseConfig "visualizer"
            Invoke-Stage "[STEP 1/3] Formal search" (@("-m", "formal_disk4", "run", "--config", $SearchConfig) + $ExtraArguments)
            Invoke-Stage "[STEP 2/3] Single-piece geometry" (@("-m", "formal_disk4", "geometry", "--config", $GeometryConfig) + $ExtraArguments)
            Invoke-Stage "[STEP 3/3] Mapping-derived viewer" @("-m", "formal_disk4", "visualize", "--config", $VisualizerConfig)
        }
    }

    Write-Host ""
    Write-Host "[SUCCESS] Case command completed successfully."
}
catch {
    $ExitCode = 8
    Write-Host ""
    Write-Host "[ERROR] Case command failed." -ForegroundColor Red
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Write-Host "[INFO] Exit code: $ExitCode"
    Write-Host "[INFO] Log file: $LogFile"
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
}

exit $ExitCode
