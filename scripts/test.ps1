$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDirectory "tests_$Timestamp.log"
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
    Write-Host "Formal Contour Solver - Test Suite"
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

    Write-Host "[INFO] Python executable: $Python"
    & $Python --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[INFO] Running bundled unit and integration tests..."
    Write-Host "[INFO] Command: $Python -m formal_disk4 self-test"
    Write-Host ""

    & $Python -m formal_disk4 self-test
    $ExitCode = $LASTEXITCODE

    Write-Host ""
    if ($ExitCode -eq 0) {
        Write-Host "[SUCCESS] All tests passed."
    }
    else {
        Write-Host "[ERROR] Test suite failed with exit code $ExitCode." -ForegroundColor Red
    }
}
catch {
    $ExitCode = 7
    Write-Host ""
    Write-Host "[ERROR] Test execution failed." -ForegroundColor Red
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Write-Host "[INFO] Test script exit code: $ExitCode"
    Write-Host "[INFO] Log file: $LogFile"

    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $ExitCode
