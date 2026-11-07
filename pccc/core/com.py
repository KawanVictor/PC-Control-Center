"""Inicialização de COM por thread.

Objetos COM (WMI, atalhos .lnk, WinRT) presos em ciclos de referência são liberados pelo
coletor de lixo do Python em QUALQUER thread. Se essa thread não tiver COM inicializado, o
Windows encerra o processo (CO_E_NOTINITIALIZED / 0x800401F0). Por isso toda thread de
trabalho do app chama ``ensure_com()`` ao iniciar.
"""
from __future__ import annotations

import threading

_local = threading.local()


def ensure_com(multithreaded: bool = True) -> None:
    if getattr(_local, "ready", False):
        return
    try:
        import pythoncom
        flag = pythoncom.COINIT_MULTITHREADED if multithreaded else pythoncom.COINIT_APARTMENTTHREADED
        pythoncom.CoInitializeEx(flag)
    except Exception:
        pass  # já inicializado com outro modelo nesta thread: tudo bem
    _local.ready = True
