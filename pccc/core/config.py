"""Gerenciador de configurações.

Os valores padrão vêm de ``config/default_settings.json`` (empacotado com o app) e são
mesclados com o arquivo do usuário em %APPDATA%. As chaves são acessadas por caminho
pontuado, ex.: ``settings.get("appearance.accent")``.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from typing import Any

from PySide6.QtCore import QObject, Signal

from .logger import get_logger
from .paths import resource_path, settings_file

log = get_logger("config")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings(QObject):
    """Configurações persistentes. Emite ``changed(chave, valor)`` a cada alteração."""

    changed = Signal(str, object)
    _instance: "Settings | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._defaults = self._load_json(resource_path("config", "default_settings.json"))
        user = self._load_json(settings_file())
        self._data = _deep_merge(self._defaults, user)

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = Settings()
        return cls._instance

    @staticmethod
    def _load_json(path) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning("Não foi possível ler %s: %s (usando padrões)", path, e)
            # Guarda o arquivo danificado antes que o próximo salvamento o substitua.
            if isinstance(e, (json.JSONDecodeError, UnicodeDecodeError)) and path == settings_file():
                try:
                    bad = path.with_name(f"settings.corrompido-{time.strftime('%Y%m%d-%H%M%S')}.json")
                    os.replace(path, bad)
                    log.warning("Cópia do arquivo danificado guardada em %s", bad)
                except OSError:
                    pass
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any, save: bool = True) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) == value:
            return
        node[parts[-1]] = value
        if save:
            self.save()
        self.changed.emit(key, value)

    def save(self) -> None:
        """Grava de forma atômica (arquivo temporário + rename) para nunca corromper."""
        path = settings_file()
        try:
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            log.error("Falha ao salvar configurações: %s", e)

    def reset(self) -> None:
        self._data = copy.deepcopy(self._defaults)
        self.save()
        self.changed.emit("*", None)
