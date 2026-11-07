"""Backup e restauração de valores do Registro.

Regra de segurança do app: NENHUM valor do Registro é alterado sem antes ser copiado para a
tabela ``registry_backups`` do SQLite. Qualquer alteração pode ser desfeita:

* ``restore(id)``        — um valor
* ``restore_group(grp)`` — todos os valores de uma ação (ex.: trocar a cor de destaque
                           grava ~8 valores; desfazer restaura todos juntos, na ordem inversa)

Se a gravação precisou CRIAR chaves que não existiam, elas são anotadas e removidas ao desfazer
(desde que estejam vazias) — o Registro volta exatamente ao estado anterior.
"""
from __future__ import annotations

import json
import time
import uuid
import winreg

from .database import Database
from .logger import get_logger, log_operation

log = get_logger("regbackup")

HIVE_NAMES = {winreg.HKEY_CURRENT_USER: "HKCU", winreg.HKEY_LOCAL_MACHINE: "HKLM",
              winreg.HKEY_CLASSES_ROOT: "HKCR"}
HIVES = {v: k for k, v in HIVE_NAMES.items()}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    hive TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    existed INTEGER NOT NULL,
    type INTEGER,
    data BLOB,
    reason TEXT,
    restored INTEGER NOT NULL DEFAULT 0
);
"""
_MIGRATIONS = [("grp", "TEXT"), ("created_keys", "TEXT")]


def _db():
    db = Database.instance()
    if not getattr(db, "_regbackup_ready", False):
        with db._lock:
            db._conn.executescript(_SCHEMA)
            cols = {r[1] for r in db._conn.execute("PRAGMA table_info(registry_backups)")}
            for col, typ in _MIGRATIONS:
                if col not in cols:
                    db._conn.execute(f"ALTER TABLE registry_backups ADD COLUMN {col} {typ}")
            db._conn.commit()
        db._regbackup_ready = True
    return db


def new_group() -> str:
    return uuid.uuid4().hex[:12]


def _encode(value, vtype) -> bytes:
    if vtype == winreg.REG_BINARY:
        return bytes(value or b"")
    if vtype in (winreg.REG_DWORD, winreg.REG_QWORD):
        return str(int(value)).encode()
    if vtype == winreg.REG_MULTI_SZ:
        return "\x00".join(value).encode("utf-8")
    return str(value).encode("utf-8")


def _decode(data: bytes, vtype):
    if vtype == winreg.REG_BINARY:
        return bytes(data or b"")
    if vtype in (winreg.REG_DWORD, winreg.REG_QWORD):
        return int(data.decode())
    if vtype == winreg.REG_MULTI_SZ:
        return data.decode("utf-8").split("\x00") if data else []
    return data.decode("utf-8")


def _key_exists(hive: int, path: str) -> bool:
    try:
        winreg.OpenKey(hive, path).Close()
        return True
    except OSError:
        return False


def _missing_keys(hive: int, path: str) -> list[str]:
    """Chaves do caminho que ainda não existem (da mais rasa para a mais profunda)."""
    parts = path.split("\\")
    missing = []
    for i in range(1, len(parts) + 1):
        sub = "\\".join(parts[:i])
        if not _key_exists(hive, sub):
            missing.append(sub)
    return missing


def read_value(hive: int, path: str, name: str, default=None):
    try:
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def backup(hive: int, path: str, name: str, reason: str, group: str | None = None,
           created_keys: list[str] | None = None) -> int:
    """Copia o valor atual (ou registra que ele não existia). Retorna o id do backup."""
    existed, vtype, data = 0, None, None
    try:
        with winreg.OpenKey(hive, path) as k:
            value, vtype = winreg.QueryValueEx(k, name)
            existed, data = 1, _encode(value, vtype)
    except OSError:
        pass
    db = _db()
    with db._lock:
        cur = db._conn.execute(
            "INSERT INTO registry_backups (ts, hive, path, name, existed, type, data, reason, grp, created_keys) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(time.time()), HIVE_NAMES.get(hive, str(hive)), path, name, existed, vtype, data, reason, group,
             json.dumps(created_keys or [])))
        db._conn.commit()
        return cur.lastrowid


def set_value(hive: int, path: str, name: str, vtype: int, value, reason: str, group: str | None = None) -> int:
    """Faz backup e grava o valor. Lança PermissionError se faltar permissão."""
    missing = _missing_keys(hive, path)
    # Abre para escrita primeiro: sem permissão, falha antes de registrar um backup inútil.
    with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE) as k:
        bid = backup(hive, path, name, reason, group, missing)
        try:
            winreg.SetValueEx(k, name, 0, vtype, value)
        except OSError:
            # O Windows pode proteger valores específicos mesmo com a chave gravável
            # (ex.: botão Widgets no Windows 11 24H2+). Não deixa backup órfão.
            db = _db()
            with db._lock:
                db._conn.execute("DELETE FROM registry_backups WHERE id = ?", (bid,))
                db._conn.commit()
            raise
    log_operation("registry.set", f"{HIVE_NAMES.get(hive)}\\{path}\\{name or '(Padrão)'} (backup #{bid}) — {reason}")
    return bid


def delete_value(hive: int, path: str, name: str, reason: str, group: str | None = None) -> int | None:
    """Faz backup e apaga o valor (volta ao padrão do Windows). None se não existia."""
    if read_value(hive, path, name, _MISSING) is _MISSING:
        return None
    with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as k:
        bid = backup(hive, path, name, reason, group)
        winreg.DeleteValue(k, name)
    log_operation("registry.delete", f"{HIVE_NAMES.get(hive)}\\{path}\\{name} (backup #{bid}) — {reason}")
    return bid


_MISSING = object()


def _remove_if_empty(hive: int, path: str) -> None:
    try:
        with winreg.OpenKey(hive, path) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys == 0 and values == 0:
            winreg.DeleteKey(hive, path)
    except OSError:
        pass


def restore(backup_id: int) -> None:
    db = _db()
    with db._lock:
        row = db._conn.execute(
            "SELECT hive, path, name, existed, type, data, created_keys FROM registry_backups WHERE id = ?",
            (backup_id,)).fetchone()
    if row is None:
        raise KeyError(backup_id)
    hive_name, path, name, existed, vtype, data, created = row
    hive = HIVES[hive_name]
    if existed:
        with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, _decode(data, vtype))
    elif _key_exists(hive, path):
        with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
    # Remove chaves que a alteração criou (da mais profunda para a mais rasa), se vazias.
    for sub in reversed(json.loads(created or "[]")):
        _remove_if_empty(hive, sub)
    with db._lock:
        db._conn.execute("UPDATE registry_backups SET restored = 1 WHERE id = ?", (backup_id,))
        db._conn.commit()
    log_operation("registry.restore", f"backup #{backup_id}: {hive_name}\\{path}\\{name}")


def restore_group(group: str) -> int:
    """Desfaz todas as gravações de uma ação, na ordem inversa. Retorna quantas restaurou."""
    db = _db()
    with db._lock:
        ids = [r[0] for r in db._conn.execute(
            "SELECT id FROM registry_backups WHERE grp = ? AND restored = 0 ORDER BY id DESC", (group,))]
    for bid in ids:
        restore(bid)
    return len(ids)


def last_backups(limit: int = 50, reason_prefix: str = "") -> list[tuple]:
    db = _db()
    with db._lock:
        return db._conn.execute(
            "SELECT id, ts, hive, path, name, reason, restored FROM registry_backups "
            "WHERE reason LIKE ? ORDER BY id DESC LIMIT ?", (reason_prefix + "%", limit)).fetchall()
