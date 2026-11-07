"""Energia: modo de energia do Windows 11 e planos de energia.

* Modo de energia (Configurações → Sistema → Energia → Modo de energia): "Melhor eficiência",
  "Equilibrado" e "Melhor desempenho". Aplicado com ``PowerSetActiveOverlayScheme`` (a mesma
  função usada pelo controle deslizante do Windows).
* Planos de energia clássicos (powercfg): trocados com ``powercfg /setactive`` — a ferramenta
  oficial do Windows. Nada é criado nem apagado.
"""
from __future__ import annotations

import ctypes
import re
import uuid

from ..core.logger import get_logger, log_operation
from ..core.winapi import run_hidden

log = get_logger("power")

OVERLAYS = {
    "efficiency": ("961cc777-2547-4f9d-8174-7d86181b8a7a", "Melhor eficiência"),
    "balanced": ("00000000-0000-0000-0000-000000000000", "Equilibrado"),
    "performance": ("ded574b5-45a0-4f42-8737-46345c09c238", "Melhor desempenho"),
}


def _guid_bytes(s: str):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def current_overlay() -> str:
    g = (ctypes.c_byte * 16)()
    try:
        if ctypes.WinDLL("powrprof").PowerGetEffectiveOverlayScheme(ctypes.byref(g)) != 0:
            return ""
    except (OSError, AttributeError):
        return ""
    cur = str(uuid.UUID(bytes_le=bytes(g)))
    return next((k for k, (gid, _l) in OVERLAYS.items() if gid == cur), "balanced")


def set_overlay(mode: str) -> None:
    if mode not in OVERLAYS:
        raise ValueError("Modo de energia inválido")
    gid, label = OVERLAYS[mode]
    rc = ctypes.WinDLL("powrprof").PowerSetActiveOverlayScheme(ctypes.byref(_guid_bytes(gid)))
    if rc != 0:
        log_operation("power.mode", label, f"erro {rc}")
        raise OSError(f"O Windows recusou o modo de energia (código {rc}).")
    log_operation("power.mode", label)


def plans() -> list[tuple[str, str, bool]]:
    """[(guid, nome, ativo)] dos planos de energia."""
    out = run_hidden(["powercfg", "/list"], timeout=10)
    res = []
    for m in re.finditer(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+\(([^)]*)\)\s*(\*)?",
                         out, re.I):
        res.append((m.group(1).lower(), m.group(2).strip(), bool(m.group(3))))
    return res


def active_plan() -> str:
    return next((g for g, _n, a in plans() if a), "")


def set_plan(guid: str) -> None:
    known = {g: n for g, n, _a in plans()}
    guid = (guid or "").lower()
    if guid not in known:
        raise ValueError("Plano de energia não encontrado.")
    run_hidden(["powercfg", "/setactive", guid], timeout=10)
    if active_plan() != guid:
        raise OSError("O Windows não ativou o plano de energia.")
    log_operation("power.plan", known[guid])


def state() -> dict:
    return {"overlay": current_overlay(), "plan": active_plan()}


def restore(st: dict) -> None:
    if st.get("plan") and st["plan"] != active_plan():
        try:
            set_plan(st["plan"])
        except (ValueError, OSError) as e:
            log.info("Plano anterior não restaurado: %s", e)
    if st.get("overlay") and st["overlay"] != current_overlay():
        set_overlay(st["overlay"])
