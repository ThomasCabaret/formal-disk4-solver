$ErrorActionPreference = "Stop"

function Split-ExtraArguments {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return @()
    }
    $Pattern = '(?:[^\s"]+|"[^"]*")+'
    return @([regex]::Matches($CommandLine, $Pattern) | ForEach-Object {
        $_.Value.Replace('"', '')
    })
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDirectory "pizza3_full_pipeline_$Timestamp.log"
$TranscriptStarted = $false
$ExitCode = 0

try {
    try {
        Start-Transcript -Path $LogFile -Append | Out-Null
        $TranscriptStarted = $true
    }
    catch {
        Write-Warning "Could not start the transcript log: $($_.Exception.Message)"
    }

    Write-Host "============================================================"
    Write-Host "Formal Contour Solver - Complete Pizza Pipeline"
    Write-Host "Working directory: $ProjectRoot"
    Write-Host "Log file: $LogFile"
    Write-Host "============================================================"
    Write-Host ""

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

    $ExtraArguments = Split-ExtraArguments $env:FORMAL_DISK4_EXTRA_ARGS
    $Restart = $ExtraArguments -contains "--restart"
    $Unknown = @($ExtraArguments | Where-Object { $_ -ne "--restart" })
    if ($Unknown.Count -gt 0) {
        throw "Unsupported full-pipeline argument(s): $($Unknown -join ' '). Only --restart is accepted."
    }

    Write-Host "[INFO] Python executable: $Python"
    & $Python --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed with exit code $LASTEXITCODE."
    }
    if ($Restart) {
        Write-Host "[INFO] Restart requested: formal and geometry checkpoints will be discarded."
    }
    else {
        Write-Host "[INFO] Resume mode: existing formal and geometry checkpoints will be reused."
    }

    $FormalArguments = @("-m", "formal_disk4", "run", "--config", "config\pizza3.json")
    if ($Restart) { $FormalArguments += "--restart" }
    Write-Host ""
    Write-Host "[STEP 1/3] Searching for a decorated formal pizza profile..."
    Write-Host "[INFO] Command: $Python $($FormalArguments -join ' ')"
    & $Python @FormalArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Formal search failed with exit code $LASTEXITCODE."
    }

    $GeometryArguments = @("-m", "formal_disk4", "geometry", "--config", "config\pizza3_geometry.json")
    if ($Restart) { $GeometryArguments += "--restart" }
    Write-Host ""
    Write-Host "[STEP 2/3] Realizing the single-piece contour geometrically..."
    Write-Host "[INFO] Command: $Python $($GeometryArguments -join ' ')"
    & $Python @GeometryArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Geometry realization failed with exit code $LASTEXITCODE."
    }

    $VisualizerArguments = @("-m", "formal_disk4", "visualize", "--config", "config\pizza3_visualizer.json")
    Write-Host ""
    Write-Host "[STEP 3/3] Reconstructing mapped copies and opening the viewer..."
    Write-Host "[INFO] Close the graphical window to complete this script."
    Write-Host "[INFO] Command: $Python $($VisualizerArguments -join ' ')"
    & $Python @VisualizerArguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "Visualizer failed with exit code $ExitCode."
    }

    Write-Host ""
    Write-Host "[SUCCESS] Complete pizza pipeline finished successfully."
}
catch {
    if ($ExitCode -eq 0) { $ExitCode = 8 }
    Write-Host ""
    Write-Host "[ERROR] Complete pizza pipeline failed." -ForegroundColor Red
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Write-Host "[INFO] Full-pipeline script exit code: $ExitCode"
    Write-Host "[INFO] Log file: $LogFile"
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $ExitCode
