"""Mídia em reprodução via Controles de Transporte de Mídia do Windows (WinRT).

É a mesma fonte do painel de mídia do Windows (volume/Central de ações): funciona com
Spotify, YouTube no navegador, Groove/Media Player, VLC recente, etc. Roda em uma thread
com laço asyncio próprio e só é iniciado quando existe um widget de player.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from dataclasses import dataclass

from ..core.logger import get_logger

log = get_logger("media")

APP_NAMES = {"spotify": "Spotify", "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
             "zunemusic": "Media Player", "microsoft.media.player": "Media Player", "vlc": "VLC",
             "opera": "Opera", "brave": "Brave", "deezer": "Deezer", "amazon": "Amazon Music",
             "applemusic": "Apple Music", "tidal": "TIDAL", "youtube": "YouTube Music"}


@dataclass
class MediaInfo:
    available: bool = False         # API disponível
    active: bool = False            # existe sessão
    title: str = ""
    artist: str = ""
    album: str = ""
    app: str = ""
    playing: bool = False
    position: float = 0.0           # segundos
    duration: float = 0.0
    updated: float = 0.0            # quando position foi lida (para interpolar)
    thumbnail: bytes = b""
    error: str = ""

    def live_position(self) -> float:
        if self.playing and self.duration:
            return min(self.duration, self.position + (time.time() - self.updated))
        return self.position


def _friendly_app(aumid: str) -> str:
    low = aumid.lower()
    for k, v in APP_NAMES.items():
        if k in low:
            return v
    base = aumid.split("!")[0].split("\\")[-1].replace(".exe", "")
    return base.split("_")[0].split(".")[-1] or "Mídia"


class MediaService:
    _instance: "MediaService | None" = None

    def __init__(self) -> None:
        self.info = MediaInfo()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_title: str | None = None
        self._mgr: Any = None             # gerenciador de sessões WinRT

    @classmethod
    def instance(cls) -> "MediaService":
        if cls._instance is None:
            cls._instance = MediaService()
        return cls._instance

    def ensure_started(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="MediaService", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Encerra o laço e ESPERA a thread: objetos WinRT vivos durante o encerramento do
        Python derrubam o processo."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def snapshot(self) -> MediaInfo:
        with self._lock:
            return self.info

    # ---------------------------------------------------------------- laço
    def _run(self) -> None:
        from ..core.com import ensure_com
        ensure_com()   # WinRT/COM nesta thread (ver core/com.py)
        try:
            from winrt.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as Manager  # noqa: N813
        except Exception as e:
            with self._lock:
                self.info = MediaInfo(available=False, error=f"API de mídia indisponível: {e}")
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def main():
            try:
                self._mgr = await Manager.request_async()
            except Exception as e:
                with self._lock:
                    self.info = MediaInfo(available=False, error=str(e))
                return
            while not self._stop.is_set():
                try:
                    await self._poll()
                except Exception as e:
                    log.debug("mídia: %s", e)
                for _ in range(10):               # dorme 1 s, mas reage ao stop em 0,1 s
                    if self._stop.is_set():
                        break
                    await asyncio.sleep(0.1)
            self._mgr = None

        try:
            self._loop.run_until_complete(main())
        finally:
            with self._lock:
                self.info = MediaInfo(available=True)   # solta referências WinRT nesta thread
            self._loop.close()
            self._loop = None
            import gc
            gc.collect()

    async def _poll(self) -> None:
        s = self._mgr.get_current_session()
        if s is None:
            with self._lock:
                self.info = MediaInfo(available=True, active=False)
            self._last_title = None
            return
        props = await s.try_get_media_properties_async()
        if props is None:
            return
        pb = s.get_playback_info()
        tl = s.get_timeline_properties()
        title = props.title or ""
        thumb = self.info.thumbnail if title == self._last_title else b""
        if title != self._last_title and props.thumbnail is not None:
            thumb = await self._read_thumb(props.thumbnail)
        self._last_title = title
        info = MediaInfo(
            available=True, active=True, title=title, artist=props.artist or "", album=props.album_title or "",
            app=_friendly_app(s.source_app_user_model_id or ""),
            playing=int(pb.playback_status) == 4,   # 4 = Playing
            position=tl.position.total_seconds() if hasattr(tl.position, "total_seconds") else 0.0,
            duration=tl.end_time.total_seconds() if hasattr(tl.end_time, "total_seconds") else 0.0,
            updated=time.time(), thumbnail=thumb)
        # A posição do Windows só atualiza quando o player avisa: corrigimos pelo horário.
        try:
            lu = tl.last_updated_time
            age = time.time() - lu.timestamp() if hasattr(lu, "timestamp") else 0
            if info.playing and 0 < age < 3600:
                info.position += age
        except Exception:
            pass
        with self._lock:
            self.info = info

    async def _read_thumb(self, ref) -> bytes:
        try:
            from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
            stream = await ref.open_read_async()
            buf = Buffer(min(int(stream.size), 4 * 1024 * 1024))
            await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
            reader = DataReader.from_buffer(buf)
            data = bytearray(buf.length)
            reader.read_bytes(data)
            return bytes(data)
        except Exception as e:
            log.debug("capa: %s", e)
            return b""

    # ------------------------------------------------------------- controles
    def command(self, action: str) -> None:
        """play_pause | next | previous"""
        if self._loop is None:
            return

        async def run():
            s = self._mgr.get_current_session()
            if s is None:
                return
            if action == "play_pause":
                await s.try_toggle_play_pause_async()
            elif action == "next":
                await s.try_skip_next_async()
            elif action == "previous":
                await s.try_skip_previous_async()
            await self._poll()

        asyncio.run_coroutine_threadsafe(run(), self._loop)
