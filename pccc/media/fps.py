"""Contador de FPS de jogos, usando o PresentMon (ferramenta oficial e gratuita da Intel).

Por que precisa de administrador: o Windows só entrega os eventos de "quadro apresentado"
(ETW do DirectX/DXGI) para administradores ou membros do grupo "Usuários de log de
desempenho". Então, quando você liga o contador:

1. O app reabre A SI MESMO elevado (um aviso do UAC) em modo auxiliar: ``--fps-helper``.
2. O auxiliar confere a assinatura digital da Intel no PresentMon.exe (com o arquivo
   travado contra alteração), executa-o e resume os quadros num arquivo pequeno
   (``status.json``, reescrito 2x por segundo — não cresce).
3. O app (sem privilégios) lê esse resumo. Desligar = o app cria o arquivo ``stop`` e o
   auxiliar encerra o PresentMon. Se o app fechar, o auxiliar percebe e encerra também.

O PresentMon é baixado do GitHub oficial da Intel (GameTechDev/PresentMon) somente quando
você pede, para %LOCALAPPDATA%\\PCControlCenter\\tools.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ..core.logger import get_logger, log_operation
from ..core.safety import delete_app_file

log = get_logger("fps")

RELEASES_API = "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
DOWNLOAD_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
                  "release-assets.githubusercontent.com"}
SIGNER = "Intel Corporation"
SESSION = "PCControlCenter_FPS"
IGNORE = {"dwm.exe", "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
          "shellexperiencehost.exe", "applicationframehost.exe", "pc control center.exe", "python.exe",
          "pythonw.exe", "presentmon.exe"}


def tools_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PCControlCenter" / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def presentmon_path() -> Path:
    return tools_dir() / "PresentMon.exe"


def work_dir() -> Path:
    from ..core.paths import data_dir
    d = data_dir() / "fps"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------- download
def _get(url: str, timeout: float = 30) -> bytes:
    if not url.startswith("https://") or urllib.parse.urlparse(url).hostname not in DOWNLOAD_HOSTS:
        raise ValueError(f"Endereço não permitido: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PCControlCenter", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = urllib.parse.urlparse(r.geturl()).hostname
        if final not in DOWNLOAD_HOSTS:
            raise ValueError(f"Redirecionamento inesperado para {final}")
        return r.read(20_000_000)


def latest_release() -> tuple[str, str, int]:
    """(versão, url do .exe x64, tamanho em bytes) da versão estável mais recente."""
    data = json.loads(_get(RELEASES_API))
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.startswith("PresentMon-") and name.endswith("-x64.exe"):
            return data.get("tag_name", ""), a["browser_download_url"], int(a.get("size", 0))
    raise RuntimeError("Nenhum PresentMon x64 encontrado na versão mais recente.")


def signature(path: str | Path) -> tuple[bool, str]:
    """(assinatura válida da Intel?, descrição). Usa a verificação Authenticode do Windows."""
    from ..core.safety import ps_quote
    from ..core.winapi import run_hidden
    cmd = (f"$s = Get-AuthenticodeSignature -LiteralPath {ps_quote(str(path))}; "
           "$s.Status.ToString() + '|' + $s.SignerCertificate.Subject")
    out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=30).strip()
    status, _, subject = out.partition("|")
    # Ex.: "CN=Intel Corporation, O=Intel Corporation, L=Santa Clara, S=California, C=US"
    ok = status == "Valid" and f"O={SIGNER}" in subject
    return ok, (f"{status} — {subject}" if subject else status) or "sem assinatura"


def download(progress=None) -> str:
    """Baixa o PresentMon oficial, confere a assinatura e instala em tools/. Retorna a versão."""
    tag, url, size = latest_release()
    if progress:
        progress(f"Baixando PresentMon {tag} ({size / 1e6:.1f} MB)...")
    data = _get(url, timeout=120)
    tmp = tools_dir() / "PresentMon.download"
    tmp.write_bytes(data)
    ok, desc = signature(tmp)
    if not ok:
        delete_app_file(tmp)
        log_operation("fps.download", url, f"recusado: assinatura {desc}")
        raise RuntimeError(f"Assinatura digital inválida ({desc}). O arquivo foi descartado.")
    os.replace(tmp, presentmon_path())
    (tools_dir() / "PresentMon.version").write_text(tag, encoding="utf-8")
    log_operation("fps.download", f"PresentMon {tag} ({desc})")
    return tag


def installed_version() -> str:
    try:
        return (tools_dir() / "PresentMon.version").read_text(encoding="utf-8").strip()
    except OSError:
        return "" if not presentmon_path().exists() else "?"


# ----------------------------------------------------------- estatísticas
@dataclass
class _Proc:
    name: str
    frames: deque = field(default_factory=lambda: deque(maxlen=6000))   # tempos de quadro (ms)
    last_seen: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=60))   # fps por segundo
    last_hist: float = 0.0


class FrameStats:
    """Resume os quadros do PresentMon por processo (testável sem o PresentMon)."""

    FRAME_COLUMNS = ("msBetweenPresents", "FrameTime", "MsBetweenPresents")

    def __init__(self) -> None:
        self.procs: dict[int, _Proc] = {}
        self._col: dict[str, int] | None = None

    def header(self, row: list[str]) -> None:
        self._col = {name.strip(): i for i, name in enumerate(row)}

    def add(self, row: list[str], now: float | None = None) -> None:
        if self._col is None:
            self.header(row)
            return
        c = self._col
        if row and row[0] == "Application":           # cabeçalho repetido
            self.header(row)
            return
        try:
            name = row[c["Application"]]
            pid = int(row[c["ProcessID"]])
            col = next(c[k] for k in self.FRAME_COLUMNS if k in c)
            ft = float(row[col])
        except (KeyError, ValueError, IndexError, StopIteration):
            return
        if not (0.05 < ft < 2000):
            return
        p = self.procs.get(pid)
        if p is None:
            p = self.procs[pid] = _Proc(name=name)
        p.frames.append(ft)
        p.last_seen = time.monotonic() if now is None else now

    @staticmethod
    def _recent(frames: deque, window_ms: float) -> list[float]:
        out: list[float] = []
        total = 0.0
        for ft in reversed(frames):
            if total + ft > window_ms and out:
                break
            out.append(ft)
            total += ft
        return out

    def summary(self, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        out: list[dict] = []
        for pid, p in list(self.procs.items()):
            if now - p.last_seen > 3.0:
                del self.procs[pid]
                continue
            last = self._recent(p.frames, 1000.0)
            if not last:
                continue
            fps = len(last) * 1000.0 / sum(last)
            # "1% mínimo" (1% low): média dos 1% quadros mais lentos dos últimos 10 s —
            # mostra os engasgos que a média esconde.
            ten = sorted(self._recent(p.frames, 10_000.0), reverse=True)
            worst = ten[:max(1, len(ten) // 100)]
            low1 = 1000.0 / (sum(worst) / len(worst)) if worst else 0.0
            if now - p.last_hist >= 1.0:
                p.history.append(round(fps, 1))
                p.last_hist = now
            out.append({"pid": pid, "name": p.name, "fps": round(fps, 1), "frame_ms": round(sum(last) / len(last), 2),
                        "low1": round(low1, 1), "history": list(p.history)})
        out.sort(key=lambda d: float(d["fps"]), reverse=True)
        return out


# ------------------------------------------------- auxiliar (roda elevado)
def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _pid_alive(pid: int) -> bool:
    import psutil
    return psutil.pid_exists(pid)


def _lock_file(path: Path):
    """Abre o arquivo impedindo alterações/exclusão enquanto o handle existir."""
    import win32con
    import win32file
    return win32file.CreateFile(str(path), win32con.GENERIC_READ, win32con.FILE_SHARE_READ, None,
                                win32con.OPEN_EXISTING, 0, None)


def helper_main(argv: list[str]) -> int:
    """--fps-helper <presentmon.exe> <status.json> <stop> <pid_do_app>"""
    exe, status_path, stop_path, parent = Path(argv[0]), Path(argv[1]), Path(argv[2]), int(argv[3])
    _remove_stop(stop_path)

    def report(**kw):
        _write_json(status_path, {"ts": time.time(), **kw})

    try:
        handle = _lock_file(exe)
    except Exception as e:     # noqa: BLE001
        report(running=False, error=f"PresentMon não encontrado: {e}")
        return 1
    ok, desc = signature(exe)
    if not ok:
        report(running=False, error=f"Assinatura do PresentMon inválida ({desc}). Baixe novamente.")
        handle.Close()
        return 1
    cmd = [str(exe), "--output_stdout", "--no_console_stats", "--stop_existing_session",
           "--session_name", SESSION]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", creationflags=0x08000000)
    except OSError as e:
        report(running=False, error=f"Não foi possível iniciar o PresentMon: {e}")
        handle.Close()
        return 1
    stats = FrameStats()
    lock = threading.Lock()

    def reader():
        for row in csv.reader(proc.stdout or ()):
            with lock:
                stats.add(row)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            time.sleep(0.5)
            if proc.poll() is not None:
                err = ((proc.stderr.read() if proc.stderr else "") or "").strip().splitlines()
                report(running=False, error="O PresentMon encerrou: " + (" ".join(err[-3:]) or f"código {proc.returncode}"))
                return 1
            if stop_path.exists() or not _pid_alive(parent):
                break
            with lock:
                summary = stats.summary()
            report(running=True, error="", procs=summary)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        handle.Close()
    report(running=False, error="")
    _remove_stop(stop_path)
    return 0


def _remove_stop(path: Path) -> None:
    """Apaga o arquivo-sinal "stop" (só dentro das pastas do app)."""
    try:
        delete_app_file(path)
    except PermissionError:
        # auxiliar elevado com outra conta de administrador: as pastas do app são outras;
        # o app (sem privilégios) apaga o sinal na próxima vez que ligar o contador.
        pass


# ------------------------------------------------------ lado do app (normal)
def foreground_pid() -> int:
    import ctypes
    from ctypes import wintypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def pick_game(procs: list[dict], fg: int) -> dict | None:
    """O jogo em foco; senão, o processo com mais quadros (ignorando o próprio Windows)."""
    candidates = [p for p in procs if p["name"].lower() not in IGNORE and p["pid"] != os.getpid()]
    for p in candidates:
        if p["pid"] == fg:
            return p
    return candidates[0] if candidates else None


class FpsMonitor:
    """Liga/desliga o auxiliar e lê o resumo. Use ``FpsMonitor.instance()``."""
    _instance: "FpsMonitor | None" = None

    def __init__(self) -> None:
        self.status_path = work_dir() / "status.json"
        self.stop_path = work_dir() / "stop"
        self._started_at = 0.0

    @classmethod
    def instance(cls) -> "FpsMonitor":
        if cls._instance is None:
            cls._instance = FpsMonitor()
        return cls._instance

    def helper_command(self) -> tuple[str, list[str]]:
        args = ["--fps-helper", str(presentmon_path()), str(self.status_path), str(self.stop_path), str(os.getpid())]
        if getattr(sys, "frozen", False):
            return sys.executable, args
        main_py = str(Path(__file__).resolve().parents[2] / "main.py")
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        return str(pyw if pyw.exists() else exe), [main_py] + args

    def start(self) -> bool:
        """Pede o UAC e inicia o auxiliar. False se o usuário recusou."""
        from ..core.winapi import shell_open
        if not presentmon_path().exists():
            raise FileNotFoundError("PresentMon não instalado")
        delete_app_file(self.stop_path)
        _write_json(self.status_path, {"ts": time.time(), "running": False, "starting": True, "error": ""})
        exe, args = self.helper_command()
        ok = shell_open(exe, subprocess.list2cmdline(args), admin=True)
        log_operation("fps.start", "contador de FPS (PresentMon)", "ok" if ok else "cancelado")
        self._started_at = time.time() if ok else 0.0
        return ok

    def stop(self) -> None:
        if self.running():
            self.stop_path.write_text("stop", encoding="utf-8")
            log_operation("fps.stop")
        self._started_at = 0.0

    def read(self) -> dict:
        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"running": False, "error": ""}
        if data.get("running") and time.time() - data.get("ts", 0) > 5:
            data["running"] = False          # auxiliar parou sem avisar
        if data.get("starting") and time.time() - data.get("ts", 0) > 25:
            data.update(starting=False, error="O auxiliar não iniciou (o aviso do UAC foi recusado?)")
        return data

    def running(self) -> bool:
        d = self.read()
        return bool(d.get("running") or d.get("starting"))

    def current(self) -> tuple[dict | None, dict]:
        """(jogo atual ou None, status completo)."""
        d = self.read()
        return pick_game(d.get("procs") or [], foreground_pid()), d
