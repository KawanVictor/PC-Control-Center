"""Vídeos novos dos seus canais do YouTube, pelo feed público (RSS) oficial do YouTube.

Não usa login nem chave de API: https://www.youtube.com/feeds/videos.xml?channel_id=UC...
Aceita o link do canal (@nome, /channel/UC..., /c/..., /user/...) e descobre o ID.
As miniaturas ficam em cache em %APPDATA%\\PCControlCenter\\cache\\youtube.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from ..core.logger import get_logger
from ..core.paths import data_dir

log = get_logger("youtube")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PCControlCenter/1.1"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
ALLOWED_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com", "i.ytimg.com"}


@dataclass
class Video:
    id: str
    title: str
    channel: str
    channel_id: str
    published: float          # timestamp
    views: int = 0
    url: str = ""
    thumb_url: str = ""


def ago(ts: float) -> str:
    d = time.time() - ts
    if d < 3600:
        return f"há {max(1, int(d // 60))} min"
    if d < 86400:
        return f"há {int(d // 3600)} h"
    days = int(d // 86400)
    return "ontem" if days == 1 else f"há {days} dias"


def fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} mi de visualizações".replace(".", ",")
    if n >= 1000:
        return f"{n / 1e3:.0f} mil visualizações"
    return f"{n} visualizações"


def _get(url: str, timeout: float = 12) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or host not in ALLOWED_HOSTS:
        raise ValueError("Endereço não permitido")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9",
                                               "Cookie": "SOCS=CAI; CONSENT=YES+1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(4_000_000)


def resolve_channel(text: str) -> tuple[str, str]:
    """Link, @nome ou ID → (channel_id, nome do canal). Levanta ValueError se não achar."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Cole o link do canal ou o @nome.")
    m = re.search(r"(UC[\w-]{22})", text)
    if m and ("/channel/" in text or CHANNEL_ID.match(text)):
        cid = m.group(1)
    else:
        if text.startswith("@"):
            url = f"https://www.youtube.com/{urllib.parse.quote(text)}"
        elif re.match(r"^[\w.-]{3,}$", text):
            url = f"https://www.youtube.com/@{urllib.parse.quote(text)}"
        else:
            if not text.startswith("http"):
                text = "https://" + text
            p = urllib.parse.urlparse(text)
            if (p.hostname or "") not in ALLOWED_HOSTS:
                raise ValueError("Isso não parece um link do YouTube.")
            url = urllib.parse.urlunparse(("https", "www.youtube.com", p.path, "", "", ""))
        html = _get(url).decode("utf-8", "replace")
        m = (re.search(r'"externalId":"(UC[\w-]{22})"', html)
             or re.search(r'<meta itemprop="identifier" content="(UC[\w-]{22})"', html)
             or re.search(r'youtube\.com/channel/(UC[\w-]{22})', html)
             or re.search(r'"channelId":"(UC[\w-]{22})"', html))
        if not m:
            raise ValueError("Canal não encontrado. Confira o link.")
        cid = m.group(1)
    videos = fetch_feed(cid)
    name = videos[0].channel if videos else _feed_title(cid)
    return cid, name


def _feed_title(cid: str) -> str:
    root = ET.fromstring(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    t = root.find("a:title", NS)
    return t.text if t is not None and t.text else cid


def _ts(iso: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def fetch_feed(cid: str) -> list[Video]:
    if not CHANNEL_ID.match(cid):
        raise ValueError("ID de canal inválido")
    root = ET.fromstring(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    channel = (root.findtext("a:title", "", NS) or cid).strip()
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", "", NS)
        if not vid:
            continue
        stats = e.find("media:group/media:community/media:statistics", NS)
        link = e.find("a:link", NS)
        out.append(Video(id=vid, title=e.findtext("a:title", "", NS), channel=channel, channel_id=cid,
                         published=_ts(e.findtext("a:published", "", NS)),
                         views=int(stats.get("views", 0)) if stats is not None else 0,
                         url=link.get("href") if link is not None else f"https://www.youtube.com/watch?v={vid}",
                         thumb_url=f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"))
    return out


# --------------------------------------------------------------------- cache
def cache_dir():
    d = data_dir() / "cache" / "youtube"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbnail(video: Video) -> bytes:
    """Miniatura (baixa uma vez e reaproveita)."""
    if not re.fullmatch(r"[\w-]{6,20}", video.id):
        return b""
    path = cache_dir() / f"{video.id}.jpg"
    if path.exists():
        return path.read_bytes()
    try:
        data = _get(video.thumb_url, timeout=8)
        path.write_bytes(data)
        return data
    except Exception as e:     # noqa: BLE001
        log.debug("Miniatura %s: %s", video.id, e)
        return b""


def fetch_all(channels: list[dict]) -> tuple[list[Video], list[str]]:
    """Busca todos os canais. Retorna (vídeos mais novos primeiro, erros)."""
    videos, errors = [], []
    for ch in channels:
        try:
            videos += fetch_feed(ch["id"])
        except Exception as e:     # noqa: BLE001
            errors.append(f"{ch.get('name', ch['id'])}: {e}")
    videos.sort(key=lambda v: v.published, reverse=True)
    _prune_thumbs({v.id for v in videos})
    return videos, errors


def _prune_thumbs(keep: set[str]) -> None:
    """Remove miniaturas de vídeos que saíram dos feeds (arquivos do próprio cache)."""
    from ..core.safety import delete_app_file
    for f in cache_dir().glob("*.jpg"):
        if f.stem not in keep and time.time() - f.stat().st_mtime > 7 * 86400:
            try:
                delete_app_file(f)
            except OSError:
                pass


def save_cache(videos: list[Video]) -> None:
    (cache_dir() / "feed.json").write_text(json.dumps([asdict(v) for v in videos[:200]]), encoding="utf-8")


def load_cache() -> list[Video]:
    try:
        return [Video(**d) for d in json.loads((cache_dir() / "feed.json").read_text(encoding="utf-8"))]
    except Exception:
        return []


# ------------------------------------------------------------- serviço (Qt)
from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402


class YouTubeFeed(QObject):
    """Mantém os vídeos atualizados (a cada 30 min) e avisa sobre vídeos novos."""
    updated = Signal()
    _instance: "YouTubeFeed | None" = None
    INTERVAL_MS = 30 * 60 * 1000

    def __init__(self) -> None:
        super().__init__()
        self.videos: list[Video] = load_cache()
        self.errors: list[str] = []
        self.thumbs: dict[str, bytes] = {}
        self.loading = False
        self.last_update = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    @classmethod
    def instance(cls) -> "YouTubeFeed":
        if cls._instance is None:
            cls._instance = YouTubeFeed()
        return cls._instance

    @staticmethod
    def channels() -> list[dict]:
        from ..core.config import Settings
        ch = Settings.instance().get("media.youtube.channels")
        return [c for c in ch if isinstance(c, dict) and CHANNEL_ID.match(c.get("id", ""))] if isinstance(ch, list) else []

    def start(self) -> None:
        if self.channels():
            self._timer.start(self.INTERVAL_MS)
            if time.time() - self.last_update > 600:
                self.refresh()

    def refresh(self) -> None:
        chans = self.channels()
        if self.loading or not chans:
            if not chans:
                self.videos = []
                self.updated.emit()
            return
        self.loading = True
        self.updated.emit()
        from ..ui.tasks import run_task

        def work():
            vids, errs = fetch_all(chans)
            thumbs = {v.id: thumbnail(v) for v in vids[:24]}
            return vids, errs, thumbs

        run_task(work, on_done=self._done, on_error=self._fail)

    def _done(self, res) -> None:
        vids, errs, thumbs = res
        old = {v.id for v in self.videos}
        fresh = [v for v in vids if v.id not in old and time.time() - v.published < 24 * 3600]
        self.videos, self.errors, self.loading = vids, errs, False
        self.thumbs.update({k: v for k, v in thumbs.items() if v})
        self.last_update = time.time()
        save_cache(vids)
        from ..core.config import Settings
        if old and fresh and Settings.instance().get("media.youtube.notify", True):
            from ..automation.engine import AlertEngine
            from ..automation.store import Alert
            v = fresh[0]
            more = f" (+{len(fresh) - 1} outro(s))" if len(fresh) > 1 else ""
            AlertEngine.instance().fire(Alert("youtube", "info", f"Vídeo novo: {v.channel}", v.title + more,
                                              None, f"shell:{v.url}"))
        self.updated.emit()

    def _fail(self, msg: str) -> None:
        self.loading = False
        self.errors = [msg]
        self.updated.emit()

    def thumb(self, video: Video) -> bytes:
        if video.id not in self.thumbs:
            p = cache_dir() / f"{video.id}.jpg"
            self.thumbs[video.id] = p.read_bytes() if p.exists() else b""
        return self.thumbs[video.id]
