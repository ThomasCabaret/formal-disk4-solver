param(
    [Parameter(Mandatory = $true)]
    [string]$Config
)

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
$ConfigStem = [System.IO.Path]::GetFileNameWithoutExtension($Config)
$LogFile = Join-Path $LogDirectory "visualizer_${ConfigStem}_$Timestamp.log"
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
    Write-Host "Formal Contour Solver - Assembly Visualizer"
    Write-Host "Working directory: $ProjectRoot"
    Write-Host "Configuration: $Config"
    Write-Host "Log file: $LogFile"
    Write-Host "============================================================"
    Write-Host ""

    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        throw "Virtual environment not found. Run setup.bat first."
    }
    $ConfigPath = Join-Path $ProjectRoot $Config
    if (-not (Test-Path $ConfigPath)) {
        throw "Configuration file not found: $ConfigPath"
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

    Write-Host "[INFO] Python executable: $Python"
    & $Python --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed with exit code $LASTEXITCODE."
    }

    $Arguments = @("-m", "formal_disk4", "visualize", "--config", $Config)
    $ExtraArguments = Split-ExtraArguments $env:FORMAL_DISK4_EXTRA_ARGS
    if ($ExtraArguments.Count -gt 0) {
        $Arguments += $ExtraArguments
        Write-Host "[INFO] Additional command-line arguments: $($ExtraArguments -join ' ')"
    }

    Write-Host ""
    Write-Host "[INFO] Validating mapping-derived isometries before opening the window..."
    Write-Host "[INFO] No geometric placement search is performed in this stage."
    Write-Host "[INFO] Close the viewer window to return to this command prompt."
    Write-Host "[INFO] Command: $Python $($Arguments -join ' ')"
    Write-Host ""

    & $Python @Arguments
    $ExitCode = $LASTEXITCODE

    Write-Host ""
    if ($ExitCode -eq 0) {
        Write-Host "[SUCCESS] Assembly visualizer closed normally."
    }
    else {
        Write-Host "[ERROR] Assembly visualizer failed with exit code $ExitCode." -ForegroundColor Red
    }
}
catch {
    $ExitCode = 8
    Write-Host ""
    Write-Host "[ERROR] Visualizer launch failed." -ForegroundColor Red
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Write-Host "[INFO] Visualizer script exit code: $ExitCode"
    Write-Host "[INFO] Log file: $LogFile"
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $ExitCode
