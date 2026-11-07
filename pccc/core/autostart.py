"""Inicialização automática com o Windows.

Usa a chave do usuário atual (HKCU\\...\\Run), que não exige administrador e pode ser
revertida a qualquer momento — também aparece em Gerenciador de Tarefas > Inicializar.
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from .logger import get_logger, log_operation
from .paths import is_frozen

log = get_logger("autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PCControlCenter"


def launch_command() -> str:
    """Comando registrado no Run. Sempre inicia minimizado na bandeja."""
    if is_frozen():
        return f'"{sys.executable}" --minimized'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    main_py = Path(__file__).resolve().parents[2] / "main.py"
    return f'"{interpreter}" "{main_py}" --minimized'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError as e:
        log.warning("Não foi possível ler a chave Run: %s", e)
        return False


def sync() -> None:
    """Se a inicialização automática está ligada mas aponta para outra instalação (ex.: a
    versão em Python antes de instalar o .EXE, ou uma pasta antiga), atualiza o caminho."""
    if not is_frozen() or not is_enabled():
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            current, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return
    if current != launch_command():
        log.info("Atualizando o caminho da inicialização automática: %s", current)
        set_enabled(True)


def set_enabled(enabled: bool) -> bool:
    """Ativa/desativa. Retorna True em caso de sucesso."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                cmd = launch_command()
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
                log_operation("autostart.enable", cmd)
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
                log_operation("autostart.disable")
        return True
    except OSError as e:
        log.error("Falha ao alterar inicialização automática: %s", e)
        log_operation("autostart.set", str(enabled), f"erro: {e}")
        return False
