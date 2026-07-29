# Keep this script ASCII-only for Windows PowerShell 5.1.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [int]$Size,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if ($Size -lt 3) {
    throw "Double-cycle size must be at least 3."
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TemplateId = "double-cycle-6"
$CaseId = "double-cycle-$Size"
$Source = Join-Path $ProjectRoot "config\cases\$TemplateId"
$Destination = Join-Path $ProjectRoot "config\cases\$CaseId"

if (-not (Test-Path $Source)) {
    throw "Template case not found: $Source"
}
if ((Test-Path $Destination) -and -not $Force) {
    throw "Case already exists: $Destination. Use -Force to overwrite it."
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Get-ChildItem -Path $Source -File -Filter "*.json" | ForEach-Object {
    $Text = Get-Content -Raw -Encoding UTF8 $_.FullName
    $Text = $Text.Replace($TemplateId, $CaseId)
    $Target = Join-Path $Destination $_.Name
    [System.IO.File]::WriteAllText($Target, $Text, [System.Text.UTF8Encoding]::new($false))
}

$ManifestPath = Join-Path $Destination "case.json"
$Manifest = Get-Content -Raw -Encoding UTF8 $ManifestPath | ConvertFrom-Json
$Manifest.id = $CaseId
$Manifest.map = $CaseId
$Manifest.label = "Double cycle $Size ($($Size * 2) tiles)"
$Manifest.description = "Two $Size-cycles of congruent tiles joined by matching E_i-I_i contacts."
$ManifestJson = $Manifest | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText(
    $ManifestPath,
    $ManifestJson + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "[SUCCESS] Created case: $CaseId"
Write-Host "[INFO] Run: .\run_case.bat $CaseId search --restart"
