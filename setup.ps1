# PC Control Center — instalação do ambiente
# Uso:  powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Cria o ambiente virtual FORA da pasta do projeto (%LOCALAPPDATA%\PCControlCenter\venv),
# porque pastas sincronizadas pelo OneDrive bloqueiam arquivos durante o pip install.

$ErrorActionPreference = "Stop"
$venv = Join-Path $env:LOCALAPPDATA "PCControlCenter\venv"

# Localiza o Python 3.11+
$python = $null
foreach ($candidate in @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"))) {
    if (Test-Path $candidate) { $python = $candidate; break }
}
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $python = $cmd.Source }
}
if (-not $python) {
    Write-Host "Python não encontrado. Instalando Python 3.12 via winget (somente para este usuário)..."
    winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    $python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
}

Write-Host "Usando Python: $python"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $python -m venv $venv
}
& (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $venv "Scripts\python.exe") -m pip install -r (Join-Path $PSScriptRoot "requirements.lock")
Write-Host ""
Write-Host "Pronto! Execute com:  run.bat   (ou: $venv\Scripts\python.exe main.py)"
