"""Caminhos usados pelo aplicativo.

Dados do usuário (configurações, banco, logs) ficam em %APPDATA%\\PCControlCenter,
nunca na pasta do programa — assim o app funciona instalado em "Arquivos de Programas"
e não sofre com bloqueios de sincronização do OneDrive.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "PCControlCenter"


def is_frozen() -> bool:
    """True quando rodando como .EXE gerado pelo PyInstaller."""
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    """Pasta raiz dos recursos do app (código ou pacote do PyInstaller)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    return base_dir().joinpath(*parts)


def data_dir() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / APP_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_file() -> Path:
    return data_dir() / "settings.json"


def database_file() -> Path:
    return data_dir() / "history.db"
