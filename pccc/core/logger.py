"""Configuração de logs.

Dois canais:
* ``pccc``            — log técnico (erros, avisos, diagnóstico) em app.log
* ``pccc.operations`` — registro de auditoria de ações executadas pelo usuário
                        (requisito de segurança) em operations.log
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_dir

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def setup_logging(debug: bool = False) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("pccc")
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    app_handler = RotatingFileHandler(log_dir() / "app.log", maxBytes=2_000_000,
                                      backupCount=3, encoding="utf-8")
    app_handler.setFormatter(logging.Formatter(_FMT))
    root.addHandler(app_handler)

    if sys.stderr is not None:  # pythonw/.exe sem console não têm stderr
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FMT))
        root.addHandler(console)

    ops = logging.getLogger("pccc.operations")
    ops_handler = RotatingFileHandler(log_dir() / "operations.log", maxBytes=2_000_000,
                                      backupCount=5, encoding="utf-8")
    ops_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    ops.addHandler(ops_handler)

    # Exceções não tratadas vão para o log em vez de sumirem silenciosamente.
    def _hook(exc_type, exc, tb):
        logging.getLogger("pccc").critical("Exceção não tratada", exc_info=(exc_type, exc, tb))
        if sys.stderr is not None:      # no .EXE sem console não há stderr
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pccc.{name}")


def log_operation(action: str, details: str = "", result: str = "ok") -> None:
    """Registra uma ação do usuário no log de auditoria e no banco (se disponível)."""
    logging.getLogger("pccc.operations").info("%s | %s | %s", action, result, details)
    try:
        from .database import Database
        Database.instance().log_operation(action, details, result)
    except Exception:  # o log em arquivo já garante o registro
        pass
