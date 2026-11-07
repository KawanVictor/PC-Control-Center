"""Testes de segurança (Fase 8).

1. Análise estática do código: comandos perigosos proibidos, escrita no Registro e exclusão de
   arquivos só nos módulos autorizados.
2. Comportamento: escape de comandos PowerShell, pastas protegidas, processos essenciais,
   backup do Registro antes de gravar (e sem backup órfão quando a gravação falha),
   recuperação de configurações e banco de dados danificados.

Usa uma pasta de dados TEMPORÁRIA e uma chave de teste em HKCU\\Software — os dados reais do
usuário e o Windows não são tocados.

Execute:  python -m tests.test_security
"""
import os
import re
import sqlite3
import sys
import tempfile
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="pccc-sec-"))
os.environ["APPDATA"] = str(TMP)          # isola configurações, banco e logs

from pccc.core.logger import setup_logging  # noqa: E402

TEST_KEY = r"Software\PCControlCenterSecurityTest"
results: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:      # noqa: BLE001
            results.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


# --------------------------------------------------------------------------- estático
SOURCES = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in (ROOT / "pccc").rglob("*.py")}


def _code_only(text: str) -> str:
    """Remove comentários e docstrings simples para não acusar textos explicativos."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _where(pattern: str) -> set[str]:
    rx = re.compile(pattern)
    return {f for f, t in SOURCES.items() if rx.search(_code_only(t))}


@check("Sem shell=True, os.system, eval ou exec de texto")
def _():
    bad = _where(r"shell\s*=\s*True|os\.system\(|(?<![\w.])eval\(|(?<![\w.])exec\(")
    assert not bad, bad


@check("Sem comandos destrutivos (serviços, boot, Remove-Item, reg delete, taskkill)")
def _():
    bad = _where(r"(?i)sc(\.exe)?\s+(config|stop|delete)|Set-Service|Stop-Service|bcdedit|Remove-Item"
                 r"|reg(\.exe)?\s+delete|taskkill|vssadmin|format\s+[a-z]:|cipher\s+/w|DisableAntiSpyware")
    assert not bad, bad


@check("Registro só é alterado por regbackup (com backup) e autostart (valor próprio)")
def _():
    writers = _where(r"winreg\.(SetValueEx|SetValue|DeleteValue|DeleteKey|DeleteKeyEx)\(")
    assert writers <= {"pccc/core/regbackup.py", "pccc/core/autostart.py"}, writers


@check("Arquivos só são apagados por safety.safe_delete_file")
def _():
    deleters = _where(r"os\.remove\(|os\.unlink\(|shutil\.rmtree\(|\.unlink\(|\.rmdir\(")
    # selftest apaga apenas os próprios arquivos temporários que acabou de criar
    assert deleters <= {"pccc/core/safety.py", "pccc/selftest.py"}, deleters


@check("Elevação (UAC) só via winapi.shell_open, por ação do usuário")
def _():
    assert _where(r'"runas"') == {"pccc/core/winapi.py"}
    # settings/apps/tools: botões "reabrir como administrador" (com confirmação);
    # tweaks: apenas MARCA os ajustes que exigem administrador (Tweak(admin=True));
    # media/fps: botão "Ligar contador" → auxiliar elevado que roda o PresentMon (assinatura conferida).
    callers = _where(r"relaunch_as_admin\(|admin\s*=\s*True")
    assert callers <= {"pccc/core/winapi.py", "pccc/ui/pages/settings.py", "pccc/ui/pages/tools.py",
                       "pccc/ui/pages/apps.py", "pccc/personalization/tweaks.py", "pccc/media/fps.py"}, callers


@check("Nenhum encerramento automático de processos")
def _():
    # processes.terminate: botão "Encerrar" (lista de essenciais bloqueada + confirmação);
    # changes.restart_explorer: botão "Reiniciar Explorer" (com confirmação), só do usuário atual.
    # media/fps: o auxiliar encerra o PRÓPRIO processo filho (PresentMon) que ele iniciou.
    users = _where(r"\bterminate\(|\.kill\(")
    assert users <= {"pccc/apps/processes.py", "pccc/personalization/changes.py", "pccc/media/fps.py"}, users
    eng = SOURCES["pccc/automation/engine.py"] + SOURCES["pccc/automation/advisor.py"]
    assert "terminate" not in eng and "restart_explorer" not in eng, "automação encerrando processos"


# ------------------------------------------------------------------------ comportamento
@check("ps_quote impede injeção no PowerShell")
def _():
    from pccc.core.safety import ps_quote
    assert ps_quote("abc") == "'abc'"
    assert ps_quote("x'; Remove-Item C:\\ -Recurse; '") == "'x''; Remove-Item C:\\ -Recurse; '''"
    for bad in ("a\nb", "a\rb", "a\0b"):
        try:
            ps_quote(bad)
        except ValueError:
            continue
        raise AssertionError(f"aceitou {bad!r}")


@check("Desinstalação da Store recusa nomes de pacote maliciosos")
def _():
    from pccc.apps.installed import store_uninstall_command
    ok = store_uninstall_command("Microsoft.Todos_2.114.7122.0_x64__8wekyb3d8bbwe")
    assert ok == "Remove-AppxPackage -Package 'Microsoft.Todos_2.114.7122.0_x64__8wekyb3d8bbwe'", ok
    for bad in ("x'; Remove-Item C:\\", "a b", "$(calc)", "", "pkg`n"):
        try:
            store_uninstall_command(bad)
        except ValueError:
            continue
        raise AssertionError(f"aceitou {bad!r}")


@check("Pastas protegidas e tipos de arquivo bloqueados")
def _():
    from pccc.core.safety import is_protected_path, safe_delete_file
    win = os.environ.get("SystemRoot", r"C:\Windows")
    for p in (win, os.path.join(win, "System32", "drivers", "x.lnk"), "C:\\", str(Path.home()),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "App", "a.lnk")):
        assert is_protected_path(p), p
    assert not is_protected_path(Path.home() / "Desktop" / "atalho.lnk")
    for p in (os.path.join(win, "notepad.exe"), str(TMP / "doc.txt"), str(TMP / "pasta.lnk.exe")):
        try:
            safe_delete_file(p, "teste")
        except PermissionError:
            continue
        raise AssertionError(f"permitiu apagar {p}")


@check("Atalho criado pelo app é apagado; pasta com nome .lnk não")
def _():
    from pccc.core.safety import safe_delete_file
    lnk = TMP / "Teste.lnk"
    lnk.write_bytes(b"L")
    assert safe_delete_file(lnk, "teste") and not lnk.exists()
    assert safe_delete_file(lnk, "teste") is False      # já não existe
    d = TMP / "Pasta.lnk"
    d.mkdir()
    try:
        safe_delete_file(d, "teste")
        raise AssertionError("apagou uma pasta")
    except PermissionError:
        assert d.exists()


@check("Arquivos internos (cache) só são apagados dentro das pastas do app")
def _():
    from pccc.core.paths import data_dir
    from pccc.core.safety import delete_app_file
    f = data_dir() / "cache" / "teste.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    assert delete_app_file(f) and not f.exists()
    outside = Path(tempfile.mkdtemp(prefix="pccc-fora-")) / "foto.jpg"
    outside.write_bytes(b"x")
    for p in (outside, data_dir() / ".." / ".." / "x.jpg"):
        try:
            delete_app_file(p)
            raise AssertionError(f"apagou fora das pastas do app: {p}")
        except PermissionError:
            pass
    assert outside.exists()


@check("Senha do OBS fica criptografada (DPAPI), nunca em texto puro")
def _():
    from pccc.core.secrets import protect, unprotect
    enc = protect("minha-senha-123")
    assert enc.startswith("dpapi:") and "minha-senha" not in enc
    assert unprotect(enc) == "minha-senha-123"
    assert unprotect("dpapi:AAAA") == "" and unprotect("texto") == ""


@check("Processos essenciais do Windows não podem ser encerrados")
def _():
    from pccc.apps.processes import ProtectedProcessError, check_killable
    from pccc.monitoring.models import ProcessEntry
    for name, pid in (("csrss.exe", 700), ("lsass.exe", 800), ("WinLogon.exe", 900), ("svchost.exe", 1000),
                      ("dwm.exe", 1100), ("System", 4), ("Idle", 0), ("python.exe", os.getpid())):
        try:
            check_killable(ProcessEntry(pid=pid, name=name, cpu=0, memory=0))
        except ProtectedProcessError:
            continue
        raise AssertionError(f"{name} poderia ser encerrado")
    # um programa comum pode ser encerrado (com confirmação na interface)
    assert check_killable(ProcessEntry(pid=99999, name="notepad.exe", cpu=0, memory=0, kind="Aplicativo")) == ""


@check("Registro: backup antes de gravar e Desfazer restaura o valor original")
def _():
    from pccc.core import regbackup
    hk = winreg.HKEY_CURRENT_USER
    try:
        with winreg.CreateKey(hk, TEST_KEY) as k:
            winreg.SetValueEx(k, "Valor", 0, winreg.REG_DWORD, 7)
        g = regbackup.new_group()
        regbackup.set_value(hk, TEST_KEY, "Valor", winreg.REG_DWORD, 1, "teste:seguranca", g)
        regbackup.set_value(hk, TEST_KEY + r"\Nova", "X", winreg.REG_SZ, "y", "teste:seguranca", g)
        assert regbackup.read_value(hk, TEST_KEY, "Valor") == 1
        assert regbackup.restore_group(g) == 2
        assert regbackup.read_value(hk, TEST_KEY, "Valor") == 7
        try:                                  # a chave criada pela alteração foi removida
            winreg.OpenKey(hk, TEST_KEY + r"\Nova").Close()
            raise AssertionError("chave criada não foi removida no Desfazer")
        except FileNotFoundError:
            pass
    finally:
        for sub in (TEST_KEY + r"\Nova", TEST_KEY):
            try:
                winreg.DeleteKey(hk, sub)
            except OSError:
                pass


@check("Registro: gravação recusada não deixa backup órfão")
def _():
    from pccc.core import regbackup
    from pccc.core.database import Database
    db = Database.instance()

    def count():
        with db._lock:
            return db._conn.execute("SELECT COUNT(*) FROM registry_backups").fetchone()[0]

    regbackup._db()
    before = count()
    real = winreg.SetValueEx

    def deny(*_a):
        raise PermissionError(5, "Acesso negado")

    winreg.SetValueEx = deny
    try:
        regbackup.set_value(winreg.HKEY_CURRENT_USER, TEST_KEY, "Negado", winreg.REG_DWORD, 1, "teste:negado")
        raise AssertionError("não propagou o erro")
    except PermissionError:
        pass
    finally:
        winreg.SetValueEx = real
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass
    assert count() == before, (before, count())


@check("Configurações danificadas: app abre com padrões e guarda uma cópia")
def _():
    from pccc.core import config
    from pccc.core.paths import settings_file
    settings_file().write_text("{ isto não é json", encoding="utf-8")
    s = config.Settings()
    assert s.get("monitoring.refresh_ms") == 1000
    copies = list(settings_file().parent.glob("settings.corrompido-*.json"))
    assert copies and "isto não é json" in copies[0].read_text(encoding="utf-8")


@check("Banco danificado: app abre com banco novo e guarda o antigo")
def _():
    from pccc.core.database import Database
    bad = TMP / "danificado.db"
    bad.write_bytes(b"SQLite format 3\0" + os.urandom(4096))
    db = Database(bad)
    assert db.recovered_from and Path(db.recovered_from).exists()
    db._conn.execute("INSERT INTO operations(ts, action) VALUES (1, 'x')")
    db.close()
    sqlite3.connect(str(bad)).execute("SELECT * FROM operations").fetchall()


def main() -> int:
    setup_logging()
    width = max(len(n) for n, _, _ in results)
    for name, ok, err in results:
        print(f"[{'OK ' if ok else 'ERRO'}] {name:<{width}}  {err}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verificações de segurança passaram")
    print("OK" if not failed else "FALHOU")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
