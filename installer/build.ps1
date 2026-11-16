param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    uv sync --extra build
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    uv run --extra build pyinstaller --noconfirm --clean --onedir --windowed --name scanow --icon app/assets/scanow.ico --add-data "app/assets/scanow.ico;app/assets" --distpath build/windows --workpath build/pyinstaller main.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    if (-not (Test-Path -LiteralPath 'build/windows/scanow/scanow.exe')) {
        throw 'The packaged ScaNow executable was not created.'
    }
    Write-Host 'Packaged ScaNow in build/windows/scanow. Prepare NAPS2, then compile scanow.iss with Inno Setup 6.'
}
finally {
    Pop-Location
}
