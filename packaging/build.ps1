param(
    [switch]$InstallDependencies,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run: py -3 -m venv .venv"
}

if ($InstallDependencies) {
    & $Python -m pip install -r (Join-Path $Root "backend\requirements.txt")
    & $Python -m pip install -r (Join-Path $Root "desktop-requirements.txt")
    & $Python -m pip install -r (Join-Path $Root "packaging\requirements-build.txt")
}

& $Python -m PyInstaller (Join-Path $Root "packaging\Yinlingban.spec") `
    --noconfirm --clean --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build\pyinstaller")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if ($Installer) {
    $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $candidates = @(
            "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        )
        $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $iscc) {
        throw "ISCC.exe not found. Install Inno Setup 6, then run this script again."
    }
    & $iscc (Join-Path $Root "packaging\installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Build complete: $Root\dist\Yinlingban"
if ($Installer) {
    Write-Host "Installer output: $Root\release"
}
