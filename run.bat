@echo off
rem Abre o PC Control Center sem janela de console.
rem Use "run.bat debug" para ver o log no console.
set VENV=%LOCALAPPDATA%\PCControlCenter\venv\Scripts
if not exist "%VENV%\pythonw.exe" (
    echo Ambiente nao encontrado. Rode primeiro: powershell -ExecutionPolicy Bypass -File setup.ps1
    pause
    exit /b 1
)
cd /d "%~dp0"
if /i "%1"=="debug" (
    "%VENV%\python.exe" main.py --debug
) else (
    start "" "%VENV%\pythonw.exe" main.py %*
)
