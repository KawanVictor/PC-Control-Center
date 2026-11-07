"""Guarda senhas (ex.: a do OBS) criptografadas com a DPAPI do Windows.

Só a sua conta do Windows, neste computador, consegue decifrar — o texto em
settings.json fica ilegível para outras contas e para quem copiar o arquivo.
"""
from __future__ import annotations

import base64

_ENTROPY = b"PCControlCenter.secret.v1"


def protect(text: str) -> str:
    if not text:
        return ""
    import win32crypt
    blob = win32crypt.CryptProtectData(text.encode("utf-8"), "PC Control Center", _ENTROPY, None, None, 0)
    return "dpapi:" + base64.b64encode(blob).decode("ascii")


def unprotect(value: str) -> str:
    if not value or not value.startswith("dpapi:"):
        return ""
    import win32crypt
    try:
        _desc, data = win32crypt.CryptUnprotectData(base64.b64decode(value[6:]), _ENTROPY, None, None, 0)
        return data.decode("utf-8")
    except Exception:
        return ""        # outra conta/computador: o usuário digita a senha de novo
