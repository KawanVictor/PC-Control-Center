"""Encerramento seguro de processos.

Regras:
* Processos essenciais do Windows (lista CRITICAL) NUNCA são encerrados — encerrar qualquer
  um deles trava ou reinicia o computador.
* Antes de encerrar, confere que o PID ainda é o mesmo processo (PIDs são reaproveitados).
* Nada é encerrado automaticamente: toda ação parte de um clique com confirmação e fica no log.
"""
from __future__ import annotations

import os

import psutil

from ..core.logger import get_logger, log_operation
from ..monitoring.models import ProcessEntry

log = get_logger("procs")

CRITICAL = {
    "system", "registry", "memory compression", "secure system", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "winlogon.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
    "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "sgrmbroker.exe", "spoolsv.exe",
    "audiodg.exe", "wudfhost.exe", "conhost.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe",
    "logonui.exe", "userinit.exe", "lsm.exe", "vmmem", "vmcompute.exe", "searchindexer.exe",
}

# Encerráveis, mas com aviso específico.
WARN = {
    "explorer.exe": "A barra de tarefas, o menu Iniciar e a área de trabalho vão sumir até o Explorer "
                    "ser reaberto (o Windows costuma reiniciá-lo sozinho).",
    "runtimebroker.exe": "Apps da Microsoft Store podem parar de funcionar até serem reabertos.",
    "startmenuexperiencehost.exe": "O menu Iniciar será reiniciado.",
    "searchhost.exe": "A pesquisa do Windows será reiniciada.",
}

FILETIME_EPOCH = 11644473600


class ProtectedProcessError(Exception):
    pass


def check_killable(e: ProcessEntry) -> str:
    """Lança ProtectedProcessError se proibido; retorna um aviso (pode ser vazio)."""
    low = e.name.lower()
    if e.pid in (0, 4) or low in CRITICAL:
        raise ProtectedProcessError(f"{e.name} é um processo essencial do Windows e não pode ser encerrado "
                                    f"por este aplicativo (o sistema poderia travar ou reiniciar).")
    if e.pid == os.getpid():
        raise ProtectedProcessError("Este é o próprio PC Control Center. Use Sair no menu da bandeja.")
    if e.kind == "Windows" and low not in WARN:
        return ("Este processo faz parte do Windows. Encerrá-lo pode fazer algum recurso do sistema parar "
                "de funcionar até a próxima reinicialização.")
    return WARN.get(low, "")


def _same_process(proc: psutil.Process, e: ProcessEntry) -> bool:
    if not e.create:
        return True
    created = e.create / 1e7 - FILETIME_EPOCH
    try:
        return abs(proc.create_time() - created) < 2.0
    except psutil.Error:
        return False


def terminate(entries: list[ProcessEntry], timeout: float = 3.0) -> tuple[list[str], list[str]]:
    """Encerra os processos. Retorna (encerrados, falhas com motivo)."""
    ok, failed = [], []
    procs = []
    for e in entries:
        try:
            check_killable(e)
            p = psutil.Process(e.pid)
            if not _same_process(p, e):
                failed.append(f"{e.name} (PID {e.pid}): o processo já terminou")
                continue
            p.terminate()  # TerminateProcess
            procs.append((p, e))
        except ProtectedProcessError as ex:
            failed.append(str(ex))
        except psutil.NoSuchProcess:
            ok.append(f"{e.name} (PID {e.pid}) já havia terminado")
        except psutil.AccessDenied:
            failed.append(f"{e.name} (PID {e.pid}): acesso negado — execute como administrador")
        except Exception as ex:
            failed.append(f"{e.name} (PID {e.pid}): {ex}")
    if procs:
        gone, alive = psutil.wait_procs([p for p, _ in procs], timeout=timeout)
        gone_pids = {p.pid for p in gone}
        for p, e in procs:
            if p.pid in gone_pids:
                ok.append(f"{e.name} (PID {e.pid})")
            else:
                failed.append(f"{e.name} (PID {e.pid}): não respondeu ao encerramento")
    log_operation("process.terminate", "; ".join(ok + failed)[:900], "ok" if not failed else "parcial")
    return ok, failed
