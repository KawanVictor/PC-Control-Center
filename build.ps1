<#
.SYNOPSIS
    Gera o executável e o instalador do PC Control Center.

.DESCRIPTION
    1. Confere o ambiente (venv do setup.ps1) e instala o PyInstaller, se faltar.
    2. Roda os testes de segurança (o build para se algum falhar).
    3. Gera o ícone (assets\app.ico) e os metadados de versão.
    4. Empacota com o PyInstaller (pccc.spec).
    5. Testa o executável gerado com --selftest.
    6. Gera o instalador com o Inno Setup (se instalado) e um .zip portátil.

    Os arquivos intermediários ficam em %LOCALAPPDATA%\PCControlCenter\build (fora do
    OneDrive, que trava arquivos durante a cópia). O resultado final vai para .\release.

.PARAMETER SkipTests
    Não roda os testes de segurança antes (o --selftest do .EXE sempre roda).

.PARAMETER NoInstaller
    Gera só a pasta do programa e o .zip portátil.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build.ps1
#>
param([switch]$SkipTests, [switch]$NoInstaller)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py   = Join-Path $env:LOCALAPPDATA "PCControlCenter\venv\Scripts\python.exe"
$work = Join-Path $env:LOCALAPPDATA "PCControlCenter\build"
$dist = Join-Path $work "dist"
$out  = Join-Path $PSScriptRoot "release"
$name = "PC Control Center"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERRO: $text" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $py)) { Fail "Ambiente não encontrado. Rode antes: powershell -ExecutionPolicy Bypass -File setup.ps1" }
$version = (& $py -c "import pccc; print(pccc.__version__)").Trim()
Write-Host "PC Control Center v$version" -ForegroundColor Green

Step "Dependências do build"
& $py -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if ($LASTEXITCODE) { Fail "pip install falhou" }

if (-not $SkipTests) {
    Step "Testes de segurança"
    & $py -m tests.test_security
    if ($LASTEXITCODE) { Fail "testes de segurança falharam — build cancelado" }
}

Step "Ícone e metadados de versão"
New-Item -ItemType Directory -Force $work | Out-Null
& $py build_tools\make_assets.py $work
if ($LASTEXITCODE) { Fail "geração do ícone falhou" }

Step "Empacotando com o PyInstaller (1 a 3 minutos)"
$env:PCCC_BUILD_WORK = $work
& $py -m PyInstaller pccc.spec --noconfirm --clean --log-level WARN --distpath $dist --workpath (Join-Path $work "pyi")
if ($LASTEXITCODE) { Fail "PyInstaller falhou" }
$exe = Join-Path $dist "$name\$name.exe"
if (-not (Test-Path $exe)) { Fail "executável não foi gerado" }
$size = (Get-ChildItem (Join-Path $dist $name) -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Pasta do programa: {0:N0} MB" -f $size)

Step "Autoteste do executável"
$p = Start-Process -FilePath $exe -ArgumentList "--selftest" -Wait -PassThru
Get-Content (Join-Path $env:APPDATA "PCControlCenter\logs\selftest.txt") -Encoding UTF8 | Write-Host
if ($p.ExitCode -ne 0) { Fail "o executável falhou no autoteste (detalhes acima e em app.log)" }

New-Item -ItemType Directory -Force $out | Out-Null

Step "Versão portátil (.zip)"
$zip = Join-Path $out "PCControlCenter-$version-portatil.zip"
# O antivírus costuma analisar o .EXE recém-criado por alguns segundos: tenta de novo.
for ($i = 1; $i -le 6; $i++) {
    try {
        if (Test-Path $zip) { Remove-Item $zip }
        Compress-Archive -Path (Join-Path $dist $name) -DestinationPath $zip -CompressionLevel Optimal -ErrorAction Stop
        break
    } catch {
        if ($i -eq 6) { Fail "não foi possível criar o .zip: $_" }
        Write-Host "Arquivo em uso (antivírus verificando?) — nova tentativa em 5 s..."
        Start-Sleep -Seconds 5
    }
}
Write-Host $zip

if (-not $NoInstaller) {
    Step "Instalador (Inno Setup)"
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
              "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
              "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        Write-Host "Inno Setup não encontrado — instalador não gerado." -ForegroundColor Yellow
        Write-Host "Para instalar (sem administrador): winget install JRSoftware.InnoSetup --scope user"
    } else {
        & $iscc /Q "/DAppVersion=$version" "/DDistDir=$(Join-Path $dist $name)" "/DOutDir=$out" "/DWorkDir=$work" installer.iss
        if ($LASTEXITCODE) { Fail "Inno Setup falhou" }
        Write-Host (Join-Path $out "PCControlCenter-Setup-$version.exe")
    }
}

Step "Pronto"
Get-ChildItem $out | Format-Table Name, @{n="Tamanho (MB)"; e={"{0:N1}" -f ($_.Length / 1MB)}} -AutoSize
