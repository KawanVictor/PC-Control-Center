# -*- mode: python ; coding: utf-8 -*-
"""Especificação do PyInstaller para o PC Control Center.

Não rode este arquivo direto — use ``build.ps1``, que gera o ícone e os metadados de
versão antes e testa o executável depois.

Formato "pasta" (onedir): abre mais rápido que um .EXE único (nada é descompactado a cada
abertura) e gera menos alarmes falsos de antivírus. O instalador (Inno Setup) empacota a pasta.
"""
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

WORK = os.environ.get("PCCC_BUILD_WORK", "build")

hidden = (
    collect_submodules("pccc")          # páginas e módulos importados sob demanda
    + collect_submodules("winrt")       # controles de mídia do Windows (widget Player)
    + collect_submodules("pycaw")       # mixer de volume (Core Audio)
    + ["win32timezone",                 # usado pelo pywin32/WMI em datas
       "win32crypt",                    # DPAPI (senha do OBS)
       "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",      # exigidos pelo pyqtgraph
       "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",  # papel de parede animado
       "PySide6.QtWebSockets",          # OBS (obs-websocket)
       "soundcard", "soundcard.mediafoundation", "_cffi_backend"]   # visualizador (loopback)
)
# O soundcard carrega as definições C (.h) em tempo de execução.
extra_datas = collect_data_files("soundcard")

# Partes grandes do Qt e bibliotecas que o app não usa (reduz ~150 MB).
excludes = [
    "tkinter", "unittest", "pydoc_data", "matplotlib", "scipy", "pandas", "IPython", "OpenGL",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtNfc",
    # NÃO excluir QtOpenGL/QtOpenGLWidgets: o pyqtgraph os importa ao carregar (o --selftest
    # acusa "No module named PySide6.QtOpenGL" se faltarem).
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("config/default_settings.json", "config"), ("assets/app.ico", "assets")] + extra_datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
    optimize=0,     # mantém docstrings/asserts: usados nas mensagens e no --selftest
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PC Control Center",
    icon="assets/app.ico",
    version=os.path.join(WORK, "version_info.txt"),
    console=False,          # app de janela (sem console preto)
    uac_admin=False,        # manifesto "asInvoker": abre SEM pedir administrador
    upx=False,              # UPX aumenta alarmes falsos de antivírus
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PC Control Center",
)
