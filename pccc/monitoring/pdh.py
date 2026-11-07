"""Leitura de contadores de desempenho do Windows (PDH).

Usa ``AddEnglishCounter`` para que os caminhos em inglês funcionem em qualquer idioma do
Windows (o sistema em português traduz os nomes dos contadores).
"""
from __future__ import annotations

import win32pdh

from ..core.logger import get_logger

log = get_logger("pdh")


class PdhQuery:
    """Conjunto de contadores coletados juntos.

    ``counters`` mapeia um apelido para o caminho em inglês. Caminhos com ``(*)`` retornam
    um dicionário {instância: valor}; os demais retornam um float.
    """

    def __init__(self, counters: dict[str, str]) -> None:
        self._paths = counters
        self._query = None
        self._handles: dict[str, int] = {}
        self._open()

    def _open(self) -> None:
        self.close()
        self._query = win32pdh.OpenQuery()
        for alias, path in self._paths.items():
            try:
                self._handles[alias] = win32pdh.AddEnglishCounter(self._query, path)
            except Exception as e:
                log.info("Contador indisponível %s: %s", path, e)
        try:
            win32pdh.CollectQueryData(self._query)  # primeira amostra (necessária p/ taxas)
        except Exception:
            pass

    def available(self, alias: str) -> bool:
        return alias in self._handles

    def collect(self) -> dict:
        if self._query is None:
            return {}
        try:
            win32pdh.CollectQueryData(self._query)
        except Exception as e:
            log.debug("CollectQueryData falhou: %s", e)
            return {}
        out: dict = {}
        for alias, h in self._handles.items():
            wildcard = "(*" in self._paths[alias]
            try:
                if wildcard:
                    out[alias] = win32pdh.GetFormattedCounterArray(h, win32pdh.PDH_FMT_DOUBLE)
                else:
                    out[alias] = win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_DOUBLE)[1]
            except Exception:
                # Instâncias que somem entre coletas (processos encerrados) geram erros
                # pontuais — apenas ignoramos esta leitura.
                out[alias] = {} if wildcard else None
        return out

    def close(self) -> None:
        if self._query is not None:
            try:
                win32pdh.CloseQuery(self._query)
            except Exception:
                pass
        self._query = None
        self._handles = {}
