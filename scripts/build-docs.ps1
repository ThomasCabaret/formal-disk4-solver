param(
    [string[]]$Sources = @(),
    [string]$OutputDirectory = "output\docs"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$docsRoot = Join-Path $projectRoot "docs"
$targetRoot = Join-Path $projectRoot $OutputDirectory
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

if ($Sources.Count -eq 0) {
    $inputs = Get-ChildItem -LiteralPath $docsRoot -Filter "*.tex" -File
} else {
    $inputs = foreach ($source in $Sources) {
        $candidate = if ([System.IO.Path]::IsPathRooted($source)) {
            $source
        } else {
            Join-Path $projectRoot $source
        }
        Get-Item -LiteralPath $candidate
    }
}

$latexmk = Get-Command latexmk -ErrorAction SilentlyContinue
$pdflatex = Get-Command pdflatex -ErrorAction SilentlyContinue
if ($null -eq $latexmk -and $null -eq $pdflatex) {
    throw "Neither latexmk nor pdflatex is available on PATH."
}

foreach ($input in $inputs) {
    Write-Host "Building $($input.Name) -> $targetRoot"
    if ($null -ne $latexmk) {
        & $latexmk.Source -pdf -interaction=nonstopmode -halt-on-error `
            -output-directory=$targetRoot $input.FullName
    } else {
        1..2 | ForEach-Object {
            & $pdflatex.Source -interaction=nonstopmode -halt-on-error `
                -output-directory=$targetRoot $input.FullName
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "LaTeX failed for $($input.FullName)"
    }
}

Write-Host "Documentation PDFs are available in $targetRoot"
