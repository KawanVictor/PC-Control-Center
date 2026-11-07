"""Papel de parede dinâmico.

Modos:
* ``bing``      — imagem do dia do Bing (troca 1x por dia)
* ``nasa``      — Foto Astronômica do Dia da NASA (APOD; nos dias em que é vídeo, mantém a anterior)
* ``folder``    — apresentação de slides com as imagens de uma pasta (intervalo e ordem aleatória)
* ``timeofday`` — uma imagem para cada período: manhã, tarde, noite e madrugada

Ao ligar, o papel de parede atual entra no Histórico de personalização: desfazer volta
para ele (e desliga o modo dinâmico). As imagens baixadas ficam em
%APPDATA%\\PCControlCenter\\wallpapers\\diario (mantidas as 14 mais recentes).
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import Settings
from ..core.logger import get_logger, log_operation
from . import changes, wallpaper

log = get_logger("dynwall")

MODES = {"bing": "Imagem do dia (Bing)", "nasa": "Foto astronômica do dia (NASA)",
         "folder": "Apresentação de slides (pasta)", "timeofday": "Por período do dia"}
PERIODS = [("morning", "Manhã (6h–12h)", 6), ("afternoon", "Tarde (12h–18h)", 12),
           ("evening", "Noite (18h–22h)", 18), ("night", "Madrugada (22h–6h)", 22)]
# apod/science/assets: onde ficam as imagens em alta (hdurl), que podem redirecionar entre si
HOSTS = {"www.bing.com", "bing.com", "api.nasa.gov", "apod.nasa.gov", "science.nasa.gov",
         "assets.science.nasa.gov"}
UA = {"User-Agent": "PCControlCenter/1.1"}


def daily_dir():
    d = wallpaper.backup_dir() / "diario"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str, timeout: float = 30) -> bytes:
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname not in HOSTS:
        raise ValueError(f"Endereço não permitido: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        if urllib.parse.urlparse(r.geturl()).hostname not in HOSTS:
            raise ValueError("Redirecionamento inesperado")
        return r.read(40_000_000)


def _save(name: str, data: bytes, meta: dict) -> str:
    if not data[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb", b"\xff\xd8\xff\xee") \
            and not data.startswith(b"\x89PNG"):
        raise ValueError("O arquivo baixado não é uma imagem JPG/PNG.")
    ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
    path = daily_dir() / f"{name}{ext}"
    path.write_bytes(data)
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _prune()
    return str(path)


def _prune(keep: int = 14) -> None:
    """Mantém só as imagens diárias mais recentes (arquivos baixados pelo próprio app)."""
    files = sorted((f for f in daily_dir().iterdir() if f.suffix in (".jpg", ".png")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    current = os.path.normcase(wallpaper.current_path())
    for f in files[keep:]:
        if os.path.normcase(str(f)) == current:
            continue
        from ..core.safety import delete_app_file
        for g in (f, f.with_suffix(".json")):
            try:
                delete_app_file(g)
            except OSError:
                pass


def fetch_bing() -> tuple[str, str]:
    """(caminho, legenda) da imagem do dia do Bing (resolução UHD)."""
    today = date.today().isoformat()
    for f in daily_dir().glob(f"bing_{today}.*"):
        if f.suffix != ".json":
            meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
            return str(f), meta.get("title", "")
    info = json.loads(_get("https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=pt-BR"))
    img = info["images"][0]
    base = img.get("urlbase") or ""
    if not re.fullmatch(r"/th\?id=[\w.\-]+", base):
        raise ValueError("Resposta inesperada do Bing")
    url = f"https://www.bing.com{base}_UHD.jpg"
    title = img.get("copyright", "") or img.get("title", "")
    return _save(f"bing_{today}", _get(url), {"title": title, "source": "Bing"}), title


def fetch_nasa() -> tuple[str, str]:
    """(caminho, legenda) da Foto Astronômica do Dia (ou a última imagem, se hoje for vídeo)."""
    today = date.today().isoformat()
    for f in daily_dir().glob(f"nasa_{today}.*"):
        if f.suffix != ".json":
            return str(f), json.loads(f.with_suffix(".json").read_text(encoding="utf-8")).get("title", "")
    key = Settings.instance().get("dynwall.nasa_key") or "DEMO_KEY"
    if not re.fullmatch(r"[\w-]{4,64}", key):
        key = "DEMO_KEY"
    try:
        info = json.loads(_get(f"https://api.nasa.gov/planetary/apod?api_key={key}&thumbs=true"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RuntimeError("Limite da chave DEMO_KEY da NASA atingido. Tente mais tarde ou use uma chave "
                               "gratuita própria (api.nasa.gov).") from None
        raise RuntimeError(f"O serviço da NASA está indisponível agora (erro {e.code}). "
                           "A imagem atual foi mantida; nova tentativa em 10 minutos.") from None
    if info.get("media_type") != "image":
        prev = sorted(daily_dir().glob("nasa_*.jpg"), reverse=True)
        if prev:
            return str(prev[0]), "Hoje a foto da NASA é um vídeo — mantida a imagem anterior."
        raise RuntimeError("Hoje a foto da NASA é um vídeo. Tente amanhã ou use outro modo.")
    url = info.get("hdurl") or info.get("url")
    title = info.get("title", "") + (f" — {info['copyright'].strip()}" if info.get("copyright") else "")
    return _save(f"nasa_{today}", _get(url, timeout=60), {"title": title, "source": "NASA APOD"}), title


def folder_images(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(wallpaper.IMAGE_EXT))


def period_now(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


def set_image(path: str, style: str | None = None) -> None:
    """Troca a imagem SEM criar entrada no histórico (o original já foi registrado ao ligar)."""
    import winreg
    from ..core import regbackup
    style = style or Settings.instance().get("dynwall.style", "fill")
    if style not in wallpaper.STYLES:
        style = "fill"
    ws, tile = wallpaper.STYLES[style]
    if wallpaper.current_style() != style:
        g = regbackup.new_group()
        regbackup.set_value(wallpaper.HKCU, wallpaper.DESKTOP, "WallpaperStyle", winreg.REG_SZ, ws, "dynwall", g)
        regbackup.set_value(wallpaper.HKCU, wallpaper.DESKTOP, "TileWallpaper", winreg.REG_SZ, tile, "dynwall", g)
    if not wallpaper._spi_set_wallpaper(os.path.abspath(path)):
        raise OSError("O Windows recusou a imagem.")


class DynamicWallpaper(QObject):
    changed = Signal(str, str)        # caminho, legenda
    failed = Signal(str)
    _instance: "DynamicWallpaper | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._busy = False
        self._retry_at = 0.0
        self.caption = ""

    @classmethod
    def instance(cls) -> "DynamicWallpaper":
        if cls._instance is None:
            cls._instance = DynamicWallpaper()
        return cls._instance

    def cfg(self) -> dict:
        return Settings.instance().get("dynwall", {}) or {}

    def start(self) -> None:
        self._timer.start(60_000)
        self.tick(force=True)

    def stop(self) -> None:
        self._timer.stop()

    def enable(self, on: bool) -> None:
        s = Settings.instance()
        if on and not s.get("dynwall.enabled"):
            remember_original("Papel de parede dinâmico ligado (imagem anterior registrada)", "dynwall")
        s.set("dynwall.enabled", on)
        log_operation("dynwall.enable" if on else "dynwall.disable", MODES.get(self.cfg().get("mode", ""), ""))
        if on:
            s.set("dynwall.last_change", 0)
            self.start()
        else:
            self.stop()

    def next_now(self) -> None:
        """Botão "Próxima imagem" (modo pasta)."""
        Settings.instance().set("dynwall.last_change", 0)
        self.tick(force=True)

    def tick(self, force: bool = False) -> None:
        c = self.cfg()
        if not c.get("enabled") or self._busy:
            return
        mode = c.get("mode", "bing")
        last = float(c.get("last_change", 0) or 0)
        now = time.time()
        if not force and now < self._retry_at:       # falhou há pouco (ex.: sem internet)
            return
        if mode in ("bing", "nasa"):
            due = force or date.fromtimestamp(last) != date.today() or now - last > 6 * 3600
        elif mode == "folder":
            due = force or now - last >= max(1, int(c.get("interval_min", 30))) * 60
        else:
            due = force or c.get("last_period") != period_now()
        if not due:
            return
        self._busy = True
        from ..ui.tasks import run_task
        run_task(self._work, mode, c, on_done=self._done, on_error=self._error)

    def _work(self, mode: str, c: dict) -> tuple[str, str, str]:
        if mode == "bing":
            path, cap = fetch_bing()
        elif mode == "nasa":
            path, cap = fetch_nasa()
        elif mode == "folder":
            imgs = folder_images(c.get("folder", ""))
            if not imgs:
                raise RuntimeError("A pasta escolhida não tem imagens.")
            cur = os.path.normcase(wallpaper.current_path())
            if c.get("shuffle", True):
                choices = [i for i in imgs if os.path.normcase(i) != cur] or imgs
                path = random.choice(choices)
            else:
                idx = next((i for i, p in enumerate(imgs) if os.path.normcase(p) == cur), -1)
                path = imgs[(idx + 1) % len(imgs)]
            cap = os.path.basename(path)
        else:
            per = period_now()
            path = (c.get("periods") or {}).get(per, "")
            if not path or not os.path.isfile(path):
                raise RuntimeError(f"Escolha a imagem para {dict((k, l) for k, l, _h in PERIODS)[per]}.")
            cap = dict((k, l) for k, l, _h in PERIODS)[per]
        set_image(path)
        return path, cap, period_now()

    def _done(self, res) -> None:
        path, cap, per = res
        self._busy = False
        self.caption = cap
        s = Settings.instance()
        s.set("dynwall.last_change", time.time(), save=False)
        s.set("dynwall.last_period", per)
        self.changed.emit(path, cap)

    def _error(self, msg: str) -> None:
        self._busy = False
        self._retry_at = time.time() + 600          # tenta de novo em 10 min
        log.warning("Papel de parede dinâmico: %s", msg)
        self.failed.emit(msg)


def remember_original(title: str, kind: str) -> int:
    """Registra o papel de parede atual no histórico (desfazer volta para ele)."""
    prev = wallpaper.current_path()
    saved = ""
    if prev and os.path.isfile(prev):
        ext = os.path.splitext(prev)[1] or ".jpg"
        saved = str(wallpaper.backup_dir() / f"anterior_{int(time.time())}{ext}")
        shutil.copy2(prev, saved)
    return changes.record(kind, title, previous_original=prev, previous=saved, style=wallpaper.current_style())
