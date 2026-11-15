$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildRoot = Join-Path $projectRoot '.build'
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
py -3.13 -m venv (Join-Path $buildRoot 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 x64 is required.' }
$pythonExe = Join-Path $buildRoot 'venv\Scripts\python.exe'
& $pythonExe -m pip install --no-deps -r (Join-Path $projectRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $pythonExe (Join-Path $projectRoot 'src\test_bridge.py')
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name PS5OBSBridge `
    --distpath $projectRoot --workpath (Join-Path $buildRoot 'pyinstaller') --specpath $buildRoot `
    --paths (Join-Path $projectRoot 'src') --collect-all av --collect-binaries _sounddevice_data `
    --collect-data certifi --collect-submodules Cryptodome --exclude-module Cryptodome.SelfTest `
    --exclude-module pyremoteplay.gui --exclude-module pyremoteplay.gamepad --exclude-module tkinter.test `
    --exclude-module pytest --hidden-import diagnostics (Join-Path $projectRoot 'src\app.py')
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
Write-Output (Join-Path $projectRoot 'PS5OBSBridge.exe')
