"""Testes reais das ações da Fase 4, sem afetar programas do usuário.

* Inicialização: cria uma entrada fictícia em HKCU\\...\\Run, desativa, confere o valor
  StartupApproved, desfaz pelo backup e remove tudo no final.
* Processos: inicia um processo Python descartável e encerra; confere que processos
  essenciais (csrss.exe, svchost.exe) são bloqueados.
* Desinstalação: registra um "programa" fictício em HKCU\\...\\Uninstall cujo desinstalador
  apenas remove a própria entrada, e executa o fluxo oficial de ponta a ponta.

Execute:  python -m tests.test_apps
"""
import subprocess
import sys
import time
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pccc.apps import startup  # noqa: E402
from pccc.apps.installed import read_registry_apps, split_command, still_installed, uninstall_plan  # noqa: E402
from pccc.apps.processes import ProtectedProcessError, check_killable, terminate  # noqa: E402
from pccc.core import regbackup  # noqa: E402
from pccc.core.logger import setup_logging  # noqa: E402
from pccc.core.winapi import shell_execute_wait  # noqa: E402
from pccc.monitoring.models import ProcessEntry  # noqa: E402
from pccc.monitoring.processes import ProcessMonitor  # noqa: E402

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINST = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
TEST = "PCCC_TesteAutomatico"


def approved_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED) as k:
            return winreg.QueryValueEx(k, TEST)[0]
    except FileNotFoundError:
        return None


def test_startup():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN) as k:
        winreg.SetValueEx(k, TEST, 0, winreg.REG_SZ, r'"C:\Windows\System32\notepad.exe"')
    try:
        item = next(i for i in startup.list_startup() if i.name == TEST)
        assert item.enabled, "entrada nova deveria estar ativada"
        before = approved_value()
        bid = startup.set_enabled(item, False)
        val = approved_value()
        assert val is not None and val[0] == 3, f"StartupApproved inesperado: {val!r}"
        item2 = next(i for i in startup.list_startup() if i.name == TEST)
        assert not item2.enabled
        regbackup.restore(bid)
        assert approved_value() == before, "desfazer não restaurou o valor original"
        print(f"inicialização: desativar → {val[:4].hex()}…, desfazer → {before!r}  OK")
    finally:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, TEST)
        if approved_value() is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, TEST)
        # Não deixa o teste aparecer no histórico de alterações do usuário.
        db = regbackup._db()
        with db._lock:
            db._conn.execute("DELETE FROM registry_backups WHERE name = ?", (TEST,))
            db._conn.commit()


def test_processes():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        time.sleep(0.5)
        pm = ProcessMonitor()
        entry = next(e for e in pm.sample().all if e.pid == proc.pid)
        ok, failed = terminate([entry])
        assert ok and not failed, (ok, failed)
        assert proc.wait(5) is not None
        print(f"processo descartável PID {entry.pid} ({entry.kind}) encerrado  OK")
    finally:
        if proc.poll() is None:
            proc.kill()
    for name in ("csrss.exe", "svchost.exe", "lsass.exe"):
        try:
            check_killable(ProcessEntry(pid=999, name=name, cpu=0, memory=0))
            raise AssertionError(f"{name} deveria ser protegido")
        except ProtectedProcessError:
            pass
    print("processos essenciais bloqueados  OK")


def test_uninstall():
    assert split_command('"C:\\A B\\u.exe" /S') == ("C:\\A B\\u.exe", "/S")
    assert split_command("C:\\x\\uninst.exe --mode=1") == ("C:\\x\\uninst.exe", "--mode=1")
    key = f"{UNINST}\\{TEST}"
    # O "desinstalador" remove a própria entrada — exatamente o que um real faz no final.
    cmd = f'"C:\\Windows\\System32\\reg.exe" delete "HKCU\\{key}" /f'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "PCCC Programa de Teste")
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, cmd)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "PC Control Center")
    try:
        app = next(a for a in read_registry_apps() if a.name == "PCCC Programa de Teste")
        exe, args, readable = uninstall_plan(app)
        assert still_installed(app)
        code = shell_execute_wait(exe, args, timeout_s=30, show=0)
        assert code == 0, code
        assert not still_installed(app), "entrada continua após o desinstalador"
        print(f"desinstalação de ponta a ponta ({readable[:60]}…)  OK")
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def main() -> int:
    setup_logging()
    test_startup()
    test_processes()
    test_uninstall()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
