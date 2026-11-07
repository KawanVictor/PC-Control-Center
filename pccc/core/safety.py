"""Regras de segurança compartilhadas.

Centraliza as verificações que protegem o sistema contra ações perigosas:

* ``ps_quote``            — coloca um texto entre aspas simples para o PowerShell sem permitir
                            injeção de comandos.
* ``is_protected_path``   — pastas e arquivos que o app nunca apaga (Windows, Arquivos de
                            Programas, raiz das unidades, a pasta do usuário etc.).
* ``safe_delete_file``    — única função do app que apaga um arquivo. Aceita só extensões
                            permitidas, recusa caminhos protegidos e registra a operação.
"""
from __future__ import annotations

import os
from pathlib import Path

from .logger import get_logger, log_operation

log = get_logger("safety")

# Extensões que o app pode apagar: apenas atalhos que ele mesmo criou.
DELETABLE_EXTENSIONS = {".lnk", ".url"}


def ps_quote(text: str) -> str:
    """Literal do PowerShell entre aspas simples (dentro delas nada é interpretado)."""
    if any(c in text for c in "\0\r\n"):
        raise ValueError("Caractere inválido para comando")
    return "'" + str(text).replace("'", "''") + "'"


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v).resolve() if v else None


def protected_roots() -> list[Path]:
    """Pastas cujo conteúdo o app nunca apaga."""
    roots = [_env_path(n) for n in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                                    "ProgramData")]
    return [r for r in roots if r is not None]


def is_protected_path(path: str | os.PathLike) -> bool:
    """True para caminhos que nunca devem ser apagados pelo app."""
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return True
    if p.parent == p:                       # raiz de unidade (C:\)
        return True
    home = Path.home().resolve()
    if p == home or p == home.parent:       # a própria pasta do usuário ou C:\Users
        return True
    for root in protected_roots():
        if p == root or root in p.parents:
            return True
    return False


def app_dirs() -> list[Path]:
    """Pastas que pertencem ao app: dados (%APPDATA%) e ferramentas/build (%LOCALAPPDATA%)."""
    from .paths import data_dir
    out = [data_dir().resolve()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append((Path(local) / "PCControlCenter").resolve())
    return out


def delete_app_file(path: str | os.PathLike) -> bool:
    """Apaga um arquivo INTERNO do app (cache, temporário, imagem baixada pelo próprio app).

    Só aceita arquivos comuns dentro das pastas do app (``app_dirs``) — nunca arquivos do
    usuário. Levanta ``PermissionError`` fora delas. Retorna False se o arquivo não existia.
    """
    p = Path(path)
    try:
        rp = p.resolve()
    except (OSError, ValueError):
        raise PermissionError(f"Caminho inválido: {p}") from None
    if not any(root in rp.parents for root in app_dirs()):
        log_operation("safety.delete_app", str(p), "recusado: fora das pastas do app")
        raise PermissionError(f"Fora das pastas do app: {p}")
    if p.is_symlink() or (p.exists() and not p.is_file()):
        raise PermissionError(f"Não é um arquivo comum: {p}")
    if not p.exists():
        return False
    os.remove(p)
    log.debug("Arquivo interno removido: %s", p)
    return True


def safe_delete_file(path: str | os.PathLike, reason: str) -> bool:
    """Apaga UM arquivo, somente se for de um tipo permitido e fora de áreas protegidas.

    Retorna True se apagou, False se o arquivo já não existia. Levanta ``PermissionError``
    se a regra de segurança recusar a operação.
    """
    p = Path(path)
    if p.suffix.lower() not in DELETABLE_EXTENSIONS:
        log_operation("safety.delete", f"{p} ({reason})", "recusado: tipo não permitido")
        raise PermissionError(f"Por segurança, o app só apaga atalhos (.lnk/.url): {p.name}")
    if is_protected_path(p):
        log_operation("safety.delete", f"{p} ({reason})", "recusado: pasta protegida")
        raise PermissionError(f"Por segurança, arquivos nesta pasta não são apagados: {p.parent}")
    if p.is_symlink() or (p.exists() and not p.is_file()):
        log_operation("safety.delete", f"{p} ({reason})", "recusado: não é um arquivo comum")
        raise PermissionError(f"Não é um arquivo comum: {p}")
    if not p.exists():
        return False
    os.remove(p)
    log_operation("safety.delete", f"{p} ({reason})")
    return True
