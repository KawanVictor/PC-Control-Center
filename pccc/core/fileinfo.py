"""Metadados de executáveis (fabricante, descrição) lidos do recurso de versão do arquivo."""
from __future__ import annotations

import os
from functools import lru_cache

import win32api


@lru_cache(maxsize=2048)
def version_info(path: str) -> dict:
    """{'company': ..., 'description': ..., 'product': ..., 'version': ...} ou {} se indisponível."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        langs = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")
        lang, cp = langs[0] if langs else (0x0409, 0x04B0)
        base = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\"

        def q(name):
            try:
                v = win32api.GetFileVersionInfo(path, base + name)
                return (v or "").strip()
            except Exception:
                return ""

        return {"company": q("CompanyName"), "description": q("FileDescription"),
                "product": q("ProductName"), "version": q("FileVersion")}
    except Exception:
        return {}
