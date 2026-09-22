$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "[1/3] Verification de l'environnement..." -ForegroundColor Cyan
python -c "import importlib.util, sys; missing=[m for m in ('PyInstaller','pkg_resources') if importlib.util.find_spec(m) is None]; sys.exit('Modules manquants: ' + ', '.join(missing)) if missing else print('Build Python dependencies OK')"
if ($LASTEXITCODE -ne 0) {
    throw 'Dependances de build manquantes. Installe d''abord un setuptools compatible, par ex. : python -m pip install "setuptools<82" pyinstaller'
}

Write-Host "[2/3] Construction PyInstaller..." -ForegroundColor Cyan
$env:QT_API = "pyside6"
python -m PyInstaller --noconfirm --clean SpectrumAirGuard.spec
if ($LASTEXITCODE -ne 0) {
    throw 'La construction PyInstaller a echoue'
}

Write-Host "[3/3] Construction de l''installateur..." -ForegroundColor Cyan
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    throw 'Inno Setup 6 est introuvable. Installe-le puis relance installer\build_installer.ps1'
}

& $iscc (Join-Path $PSScriptRoot "SpectrumAirGuard.iss")
Write-Host "Installateur genere dans le dossier release" -ForegroundColor Green
