$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDirectory "setup_$Timestamp.log"
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
    Write-Host "Formal Contour Solver - Environment Setup"
    Write-Host "Working directory: $ProjectRoot"
    Write-Host "Log file: $LogFile"
    Write-Host "============================================================"
    Write-Host ""

    $PythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $PythonLauncher) {
        throw "Python launcher 'py.exe' was not found. Install Python 3.11 or newer with the Windows launcher enabled."
    }

    Write-Host "[INFO] Python launcher found: $($PythonLauncher.Source)"

    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[INFO] No virtual environment found. Creating .venv..."

        $Created = $false
        foreach ($Version in @("3.12", "3.11", "3")) {
            Write-Host "[INFO] Trying: py -$Version -m venv .venv"
            & $PythonLauncher.Source "-$Version" -m venv .venv
            if ($LASTEXITCODE -eq 0 -and (Test-Path $VenvPython)) {
                $Created = $true
                break
            }
        }

        if (-not $Created) {
            throw "Could not create the virtual environment with Python 3.11 or newer."
        }
    }
    else {
        Write-Host "[INFO] Existing virtual environment found."
    }

    Write-Host ""
    Write-Host "[INFO] Virtual-environment Python:"
    Write-Host "       $VenvPython"
    & $VenvPython --version
    if ($LASTEXITCODE -ne 0) {
        throw "The virtual-environment Python executable could not be started."
    }

    Write-Host ""
    Write-Host "[INFO] Bootstrapping pip in the virtual environment..."
    & $VenvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        throw "ensurepip failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[INFO] Installing/upgrading packaging tools: pip, setuptools, wheel..."
    & $VenvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "Packaging-tool installation failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[INFO] Installing the project in editable mode..."
    Write-Host "[INFO] Build isolation is disabled only after setuptools and wheel have been installed explicitly."
    & $VenvPython -m pip install --no-build-isolation --editable .
    if ($LASTEXITCODE -ne 0) {
        throw "Project installation failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[INFO] Verifying imports..."
    & $VenvPython -c "import formal_disk4, numpy, scipy; print('formal_disk4', formal_disk4.__version__); print('numpy', numpy.__version__); print('scipy', scipy.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Import verification failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[SUCCESS] Installation completed successfully."
    Write-Host "[INFO] You can now run run_case.bat, run_debug.bat, run_benchmark.bat, or run_tests.bat."
}
catch {
    $ExitCode = 5
    Write-Host ""
    Write-Host "[ERROR] Setup failed." -ForegroundColor Red
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[ERROR] Review the console output and log file above."
}
finally {
    Write-Host ""
    Write-Host "[INFO] Setup script exit code: $ExitCode"
    Write-Host "[INFO] Log file: $LogFile"

    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $ExitCode
