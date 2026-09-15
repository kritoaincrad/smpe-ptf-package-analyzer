param([string]$Version = "1.0.0")

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "PTF-Analyzer-$Version" desktop_app.py
$exe = Join-Path $projectRoot "dist\PTF-Analyzer-$Version.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Build output was not created: $exe" }

if ($env:SIGN_PFX_PATH -and $env:SIGN_PFX_PASSWORD) {
    $signtool = (Get-Command signtool.exe -ErrorAction Stop).Source
    & $signtool sign /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" /f $env:SIGN_PFX_PATH /p $env:SIGN_PFX_PASSWORD $exe
    & $signtool verify /pa /v $exe
} else {
    Write-Warning "Executable is unsigned. Configure SIGN_PFX_PATH and SIGN_PFX_PASSWORD for a trusted release."
}

$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "Built: $exe"
Write-Output "SHA-256: $hash"
