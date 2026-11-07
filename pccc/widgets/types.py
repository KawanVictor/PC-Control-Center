"""Os 20 tipos de widget. Cada um desenha em seu canvas virtual (``base_size``)."""
from __future__ import annotations

import calendar
import hashlib
import math
import os
import platform
from datetime import date, datetime, timedelta

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from ..core.winapi import shell_open
from ..ui.fmt import fmt_bytes, fmt_mhz, fmt_uptime
from ..ui.icons import G
from . import weather as wx
from .base import Canvas, Renderer, fmt_rate_short
from .hub import DataHub

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
GREEN, AMBER, RED = QColor("#34d399"), QColor("#fbbf24"), QColor("#fb7185")


def heat(v: float | None, warn: float, hot: float) -> QColor:
    if v is None:
        return QColor("#94a3b8")
    return GREEN if v < warn else AMBER if v < hot else RED


def hub() -> DataHub:
    return DataHub.instance()


def _no_data(c: Canvas, msg: str = "Aguardando dados...") -> None:
    c.text(0, 0, c.w, c.h, msg, 12, color=c.s.muted, align=Qt.AlignCenter)


# ============================================================================ 1. Relógio
class ClockWidget(Renderer):
    type_id, title, glyph = "clock", "Relógio digital", G.CLOCK
    description = "Hora grande com segundos e data por extenso."
    base_size = (270, 118)
    defaults = {"h24": True, "seconds": True, "show_date": True}

    def draw(self, c: Canvas) -> None:
        now = datetime.now()
        hm = now.strftime("%H:%M") if self.opt["h24"] else now.strftime("%I:%M").lstrip("0")
        has_date = self.opt["show_date"]
        y = 6 if has_date else 18
        c.text(18, y, 190, 70, hm, 58, 600, align=Qt.AlignLeft | Qt.AlignVCenter)
        right = []
        if self.opt["seconds"]:
            right.append(now.strftime("%S"))
        if not self.opt["h24"]:
            right.append("AM" if now.hour < 12 else "PM")
        if right:
            # logo após os números grandes, alinhado à base deles
            from PySide6.QtGui import QFontMetricsF
            sx = min(18 + QFontMetricsF(c.s.font(58, 600)).horizontalAdvance(hm) + 8, 214)
            c.text(sx, y + 30, 60, 30, right[0], 22, 500, color=c.s.accent, align=Qt.AlignLeft | Qt.AlignBottom)
            if len(right) > 1:
                c.text(sx, y + 10, 60, 20, right[1], 13, 600, color=c.s.muted)
        if has_date:
            txt = f"{DIAS[now.weekday()]}, {now.day} de {MESES[now.month - 1]}"
            c.text(20, 80, 240, 26, txt, 15, 500, color=c.s.muted)


# =========================================================================== 2. Calendário
def _easter(y: int) -> date:
    a, b, cc = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = cc // 4, cc % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def br_holidays(y: int) -> dict[date, str]:
    """Feriados nacionais do Brasil (fixos + móveis)."""
    e = _easter(y)
    h = {date(y, 1, 1): "Confraternização Universal", date(y, 4, 21): "Tiradentes",
         date(y, 5, 1): "Dia do Trabalho", date(y, 9, 7): "Independência", date(y, 10, 12): "Nossa Senhora Aparecida",
         date(y, 11, 2): "Finados", date(y, 11, 15): "Proclamação da República",
         date(y, 11, 20): "Consciência Negra", date(y, 12, 25): "Natal",
         e - timedelta(days=47): "Carnaval", e - timedelta(days=48): "Carnaval",
         e - timedelta(days=2): "Sexta-feira Santa", e: "Páscoa", e + timedelta(days=60): "Corpus Christi"}
    return h


class CalendarWidget(Renderer):
    type_id, title, glyph = "calendar", "Calendário", ""
    description = "Mês atual com destaque para hoje e feriados nacionais."
    base_size = (262, 252)
    default_refresh = 60_000
    defaults = {"holidays": True, "week_start": "dom"}

    def __init__(self, cfg):
        super().__init__(cfg)
        self.offset = 0  # navegação de meses (não é salva)

    def _month(self) -> tuple[int, int]:
        t = date.today()
        m = t.month - 1 + self.offset
        return t.year + m // 12, m % 12 + 1

    def draw(self, c: Canvas) -> None:
        y, m = self._month()
        today = date.today()
        c.text(16, 10, 180, 26, f"{MESES[m - 1].capitalize()} {y}", 17, 600)
        c.glyph(200, 10, 24, 26, "", 11, c.s.muted)   # anterior
        c.glyph(228, 10, 24, 26, "", 11, c.s.muted)   # próximo
        sun_first = self.opt["week_start"] == "dom"
        heads = ["D", "S", "T", "Q", "Q", "S", "S"] if sun_first else ["S", "T", "Q", "Q", "S", "S", "D"]
        cw, x0, top = 33, 15, 44
        for i, hd in enumerate(heads):
            c.text(x0 + i * cw, top, cw, 18, hd, 11, 600, color=c.s.muted, align=Qt.AlignCenter)
        cal = calendar.Calendar(firstweekday=6 if sun_first else 0)
        hol = br_holidays(y) if self.opt["holidays"] else {}
        for r, week in enumerate(cal.monthdatescalendar(y, m)):
            for i, d in enumerate(week):
                cx, cy = x0 + i * cw, top + 22 + r * 30
                if d == today:
                    c.rounded(cx + 3, cy + 1, cw - 6, 26, 13, c.s.accent)
                color = c.s.text if d.month == m else c.s.faint
                if d == today:
                    color = QColor("#0b1020")
                elif d in hol and d.month == m:
                    color = RED
                c.text(cx, cy, cw, 28, str(d.day), 12.5, 600 if d == today else 400, color=color,
                       align=Qt.AlignCenter)
        nxt = sorted((d, n) for d, n in hol.items() if d.month == m and d >= today)
        if nxt and self.offset == 0:
            d, n = nxt[0]
            c.text(16, 226, 240, 20, f"● {d.day:02d}/{d.month:02d} — {n}", 10.5, color=RED)

    def hit_areas(self):
        return [(QRectF(200, 10, 24, 26), "prev"), (QRectF(228, 10, 24, 26), "next"),
                (QRectF(16, 10, 170, 26), "today")]

    def on_click(self, area_id: str) -> None:
        self.offset += {"prev": -1, "next": 1}.get(area_id, -self.offset)


# ================================================================================ 3. Clima
class WeatherWidget(Renderer):
    type_id, title, glyph = "weather", "Clima", ""
    description = "Tempo agora e previsão de 4 dias (Open-Meteo, sem cadastro)."
    base_size = (292, 160)
    default_refresh = 30_000
    defaults = {"city": "São Paulo", "lat": -23.5475, "lon": -46.63611, "label": "São Paulo, São Paulo"}

    def draw(self, c: Canvas) -> None:
        o = self.opt
        if o.get("lat") is None:
            _no_data(c, "Configure a cidade (botão direito → Configurar)")
            return
        data, err = hub().weather(o["lat"], o["lon"])
        c.text(16, 8, 260, 20, o.get("label") or o.get("city", ""), 12, 600, color=c.s.muted)
        if not data:
            _no_data(c, "Sem conexão com o serviço de clima" if err else "Carregando clima...")
            return
        cur = data["current"]
        desc, emoji = wx.describe(cur.get("weather_code"), bool(cur.get("is_day", 1)))
        c.text(12, 26, 64, 60, emoji, 40, family="Segoe UI Emoji", align=Qt.AlignCenter)
        c.text(80, 24, 110, 46, f"{cur['temperature_2m']:.0f}°", 40, 600)
        c.text(80, 66, 200, 18, desc, 12, 500, color=c.s.muted)
        c.text(180, 30, 100, 16, f"Sensação {cur['apparent_temperature']:.0f}°", 10.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(180, 46, 100, 16, f"Umidade {cur['relative_humidity_2m']}%", 10.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(180, 62, 100, 16, f"Vento {cur['wind_speed_10m']:.0f} km/h", 10.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        d = data["daily"]
        for i in range(1, min(5, len(d["time"]))):
            x = 14 + (i - 1) * 68
            dt = date.fromisoformat(d["time"][i])
            _desc, em = wx.describe(d["weather_code"][i])
            c.text(x, 92, 62, 16, DIAS_CURTOS[dt.weekday()], 10.5, 600, color=c.s.muted, align=Qt.AlignCenter)
            c.text(x, 106, 62, 24, em, 15, family="Segoe UI Emoji", align=Qt.AlignCenter)
            c.text(x, 130, 62, 16, f"{d['temperature_2m_max'][i]:.0f}° / {d['temperature_2m_min'][i]:.0f}°",
                   10.5, align=Qt.AlignCenter)
            pp = (d.get("precipitation_probability_max") or [None] * 9)[i]
            if pp:
                c.text(x, 144, 62, 14, f"💧{pp}%", 9, color=c.s.muted, align=Qt.AlignCenter)


# ======================================================== 4–6. CPU / RAM / GPU (anel + gráfico)
class _RingWidget(Renderer):
    base_size = (250, 128)
    label = ""
    hist_key = ""
    color: QColor | None = None

    def values(self) -> tuple[float, list[str]] | None:
        raise NotImplementedError

    def draw(self, c: Canvas) -> None:
        v = self.values()
        if v is None:
            _no_data(c)
            return
        pct, lines = v
        c.ring(56, 62, 40, pct, 8)
        c.text(16, 42, 80, 30, f"{pct:.0f}%", 20, 600, align=Qt.AlignCenter)
        c.text(16, 66, 80, 18, self.label, 10.5, 600, color=c.s.muted, align=Qt.AlignCenter)
        for i, line in enumerate(lines[:3]):
            c.text(110, 16 + i * 20, 130, 20, line, 12 if i else 13.5, 600 if i == 0 else 400,
                   color=c.s.text if i == 0 else c.s.muted)
        c.spark(110, 80, 126, 36, hub().hist[self.hist_key], vmax=100)


class CpuWidget(_RingWidget):
    type_id, title, glyph, label, hist_key = "cpu", "Monitor de CPU", G.CPU, "CPU", "cpu"
    description = "Uso do processador, frequência real e temperatura."

    def values(self):
        s = hub().sys
        if not s:
            return None
        name = s.cpu.name.replace("with Radeon Graphics", "").replace("Processor", "").strip()
        t = s.temps.cpu
        return s.cpu.percent, [name[:22], fmt_mhz(s.cpu.freq_mhz),
                               f"{t:.0f} °C" if t is not None else f"{s.cpu.threads} threads"]


class RamWidget(_RingWidget):
    type_id, title, glyph, label, hist_key = "ram", "Monitor de RAM", G.MEMORY, "RAM", "ram"
    description = "Memória em uso, disponível e histórico."

    def values(self):
        s = hub().sys
        if not s:
            return None
        m = s.memory
        return m.percent, [f"{fmt_bytes(m.used)} / {fmt_bytes(m.total)}", f"{fmt_bytes(m.available)} livre",
                           f"Virtual {fmt_bytes(m.commit_used, 0)}"]


class GpuWidget(_RingWidget):
    type_id, title, glyph, label, hist_key = "gpu", "Monitor de GPU", G.GPU, "GPU", "gpu"
    description = "Uso da placa de vídeo, VRAM e temperatura."

    def values(self):
        s = hub().sys
        g = s.primary_gpu if s else None
        if not g:
            return None
        name = g.name.replace("(TM)", "").replace("(R)", "").replace("Graphics", "").strip()
        return g.percent, [name[:22], f"VRAM {fmt_bytes(g.dedicated_used, 0)} / {fmt_bytes(g.dedicated_total, 0)}",
                           f"{g.temperature:.0f} °C" if g.temperature is not None else "Temp. N/D"]


# ========================================================================== 7. Temperatura
class TempWidget(Renderer):
    type_id, title, glyph = "temps", "Monitor de temperatura", G.TEMP
    description = "CPU, GPU e discos com cores de alerta (verde, âmbar, vermelho)."
    base_size = (250, 132)
    defaults = {"warn": 70, "hot": 85}

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s:
            _no_data(c)
            return
        c.glyph(12, 8, 22, 22, G.TEMP, 12)
        c.text(36, 8, 200, 22, "Temperaturas", 12.5, 600)
        rows = [("CPU", s.temps.cpu), ("GPU", s.temps.gpu)]
        rows += list(s.temps.disks.items())[:1]
        warn, hot = self.opt["warn"], self.opt["hot"]
        for i, (name, v) in enumerate(rows):
            y = 36 + i * 22
            col = heat(v, warn, hot)
            c.text(14, y, 70, 18, name[:10], 11.5, color=c.s.muted)
            c.bar(76, y + 6, 110, 6, (v or 0) / 1.1, col)
            c.text(190, y, 50, 18, f"{v:.0f}°" if v is not None else "N/D", 12, 600, color=col,
                   align=Qt.AlignRight | Qt.AlignVCenter)
        c.spark(14, 104, 222, 22, hub().hist["cpu_temp"], RED, vmax=110)


# ================================================================================ 8. Wi-Fi
class WifiWidget(Renderer):
    type_id, title, glyph = "wifi", "Monitor de Wi-Fi", G.NETWORK
    description = "Rede conectada, intensidade do sinal, banda e ping."
    base_size = (250, 112)

    def draw(self, c: Canvas) -> None:
        n = hub().net
        if not n:
            _no_data(c)
            return
        w = n.wifi
        bars = 0 if not w.connected else 1 + min(3, w.signal // 25)
        for i in range(4):
            h = 10 + i * 9
            col = c.s.accent if i < bars else c.s.faint
            c.rounded(18 + i * 11, 64 - h, 7, h, 2, col)
        if w.connected:
            c.text(70, 12, 172, 24, w.ssid or "(rede oculta)", 15, 600)
            c.text(70, 36, 172, 18, f"Sinal {w.signal}% · {w.rssi} dBm" if w.rssi is not None else f"Sinal {w.signal}%",
                   11.5, color=c.s.muted)
            c.text(18, 74, 230, 18, f"{w.band} · canal {w.channel} · {w.standard.split(' (')[0]}", 11,
                   color=c.s.muted)
        else:
            name = n.active.name if n.active else "Sem conexão"
            c.text(70, 12, 172, 24, "Wi-Fi desconectado" if w.available else name, 14, 600)
        p = n.ping_internet.last_ms
        status = {"online": ("Online", GREEN), "no_internet": ("Sem internet", AMBER),
                  "offline": ("Offline", RED)}.get(n.status, ("—", c.s.muted))
        c.text(18, 90, 120, 18, f"● {status[0]}", 11, 600, color=status[1])
        c.text(130, 90, 110, 18, f"Ping {p:.0f} ms" if p is not None else "Ping —", 11, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)


# ===================================================================== 9. Download/Upload
class NetSpeedWidget(Renderer):
    type_id, title, glyph = "netspeed", "Download e upload", G.DOWN
    description = "Velocidade da rede em tempo real com gráfico."
    base_size = (250, 118)
    defaults = {"bits": True}

    def draw(self, c: Canvas) -> None:
        n = hub().net
        if not n:
            _no_data(c)
            return
        down_c, up_c = QColor("#38bdf8"), QColor("#f472b6")
        c.text(14, 8, 110, 16, "↓ Download", 10.5, 600, color=down_c)
        c.text(126, 8, 110, 16, "↑ Upload", 10.5, 600, color=up_c)
        c.text(14, 22, 110, 30, fmt_rate_short(n.down_bps, self.opt["bits"]), 19, 600)
        c.text(126, 22, 110, 30, fmt_rate_short(n.up_bps, self.opt["bits"]), 19, 600)
        h = hub().hist
        top = max(max(h["down"], default=1), max(h["up"], default=1), 1024) * 1.15
        c.spark(14, 60, 222, 50, h["down"], down_c, vmax=top)
        c.spark(14, 60, 222, 50, h["up"], up_c, vmax=top, fill=False)


# ========================================================================= 10. Armazenamento
class StorageWidget(Renderer):
    type_id, title, glyph = "storage", "Monitor de armazenamento", G.DISK
    description = "Espaço livre de cada unidade e atividade do disco."
    base_size = (260, 150)

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s or not s.partitions:
            _no_data(c)
            return
        c.glyph(12, 8, 22, 22, G.DISK, 12)
        c.text(36, 8, 120, 22, "Armazenamento", 12.5, 600)
        c.text(150, 8, 96, 22, f"↓{fmt_rate_short(s.disk_io.read_bps, False)}", 9.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        parts = s.partitions[:3]
        for i, p in enumerate(parts):
            y = 36 + i * 36
            col = RED if p.percent >= 90 else AMBER if p.percent >= 80 else None
            c.text(14, y, 140, 16, f"{p.label or 'Disco'} ({p.mount.rstrip(chr(92))})", 11.5, 600)
            c.text(120, y, 126, 16, f"{fmt_bytes(p.free)} livres", 10.5, color=c.s.muted,
                   align=Qt.AlignRight | Qt.AlignVCenter)
            c.bar(14, y + 20, 232, 6, p.percent, col)


# ============================================================================ 11. Player
class MediaWidget(Renderer):
    type_id, title, glyph = "media", "Player de música", ""
    description = "O que está tocando (Spotify, navegador, Media Player) com controles."
    base_size = (310, 122)
    needs = {"media"}

    def __init__(self, cfg):
        super().__init__(cfg)
        self._thumb_key = b""
        self._thumb: QImage | None = None

    def draw(self, c: Canvas) -> None:
        m = hub().media
        if not m.available and m.error:
            _no_data(c, "Controle de mídia indisponível")
            return
        art = QRectF(14, 14, 94, 94)
        if m.thumbnail:
            key = hashlib.md5(m.thumbnail).digest()
            if key != self._thumb_key:
                self._thumb_key, self._thumb = key, QImage.fromData(m.thumbnail)
        else:
            self._thumb = None
        path = QPainterPath()
        path.addRoundedRect(art, 12, 12)
        if self._thumb is not None and not self._thumb.isNull():
            c.p.save()
            c.p.setClipPath(path)
            c.p.drawImage(art, self._thumb)
            c.p.restore()
        else:
            c.rounded(art.x(), art.y(), art.width(), art.height(), 12, c.s.faint)
            c.glyph(art.x(), art.y(), art.width(), art.height(), "", 30, c.s.muted)
        if not m.active:
            c.text(122, 30, 180, 24, "Nada tocando", 15, 600)
            c.text(122, 54, 180, 20, "Abra o Spotify, o navegador ou outro player", 10.5, color=c.s.muted)
            return
        c.text(122, 12, 180, 22, m.title or "—", 14, 600)
        c.text(122, 33, 180, 18, m.artist or m.album or "", 11.5, color=c.s.muted)
        c.text(122, 50, 180, 16, m.app, 9.5, color=c.s.accent)
        pos, dur = m.live_position(), m.duration
        if dur > 0:
            c.bar(122, 72, 176, 4, pos / dur * 100)
            c.text(122, 76, 60, 14, f"{int(pos) // 60}:{int(pos) % 60:02d}", 9, color=c.s.muted)
            c.text(238, 76, 60, 14, f"{int(dur) // 60}:{int(dur) % 60:02d}", 9, color=c.s.muted,
                   align=Qt.AlignRight | Qt.AlignVCenter)
        for rect, aid in self.hit_areas():
            g = {"previous": "", "play_pause": "" if m.playing else "", "next": ""}[aid]
            if aid == "play_pause":
                c.rounded(rect.x(), rect.y(), rect.width(), rect.height(), rect.height() / 2, c.s.accent)
                c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 12, QColor("#0b1020"))
            else:
                c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 12, c.s.text)

    def hit_areas(self):
        return [(QRectF(170, 92, 28, 26), "previous"), (QRectF(204, 91, 30, 28), "play_pause"),
                (QRectF(240, 92, 28, 26), "next")]

    def on_click(self, area_id: str) -> None:
        from .media import MediaService
        MediaService.instance().command(area_id)


# ==================================================================== 12. Info do sistema
class SysInfoWidget(Renderer):
    type_id, title, glyph = "sysinfo", "Informações do sistema", G.INFO
    description = "Computador, Windows, processador, GPU, memória e tempo ligado."
    base_size = (300, 160)
    default_refresh = 5000

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s:
            _no_data(c)
            return
        from ..monitoring.system import windows_version
        if not hasattr(self, "_os"):
            self._os = windows_version().split(" (")[0]
        g = s.primary_gpu
        c.text(14, 8, 272, 24, platform.node(), 16, 600)
        rows = [("Sistema", self._os), ("CPU", s.cpu.name.replace("with Radeon Graphics", "").strip()),
                ("GPU", g.name if g else "—"), ("Memória", f"{fmt_bytes(s.memory.total, 0)}"),
                ("Ligado há", fmt_uptime(s.uptime_s))]
        for i, (k, v) in enumerate(rows):
            y = 36 + i * 23
            c.text(14, y, 70, 20, k, 11, color=c.s.muted)
            c.text(84, y, 204, 20, v, 11.5, 500)


# ============================================================================ 13. Bateria
class BatteryWidget(Renderer):
    type_id, title, glyph = "battery", "Monitor de bateria", ""
    description = "Carga, status do carregador e tempo restante."
    base_size = (232, 104)
    default_refresh = 5000

    def draw(self, c: Canvas) -> None:
        b = hub().battery
        if b is None:
            _no_data(c, "Este computador não tem bateria")
            return
        pct = b.percent
        col = RED if pct < 20 and not b.power_plugged else AMBER if pct < 40 and not b.power_plugged else GREEN
        # corpo da bateria
        c.p.setPen(c.s.muted)
        c.p.setBrush(Qt.NoBrush)
        c.p.drawRoundedRect(QRectF(16, 28, 70, 40), 7, 7)
        c.rounded(87, 40, 5, 16, 2, c.s.muted)
        c.rounded(20, 32, 62 * pct / 100, 32, 4, col)
        if b.power_plugged:
            c.glyph(16, 28, 70, 40, "", 16, QColor("#0b1020") if pct > 55 else c.s.text)
        c.text(104, 14, 120, 40, f"{pct:.0f}%", 30, 600)
        if b.power_plugged:
            status = "Carregando" if pct < 100 else "Carregada · na tomada"
        else:
            secs = b.secsleft
            status = (f"{secs // 3600}h {secs % 3600 // 60:02d}min restantes"
                      if isinstance(secs, int) and secs > 0 else "Na bateria")
        c.text(104, 54, 124, 20, status, 11, color=c.s.muted)
        c.text(16, 76, 210, 20, "Modo economia recomendado" if pct < 20 and not b.power_plugged else "",
               10, color=RED)


# ============================================================================ 14. Atalhos
_icon_provider: QFileIconProvider | None = None
_icon_cache: dict[str, QPixmap] = {}


def _icon_for(path: str) -> QPixmap | None:
    global _icon_provider
    if path in _icon_cache:
        return _icon_cache[path]
    info = QFileInfo(path)
    pm = None
    if info.exists():
        if _icon_provider is None:
            _icon_provider = QFileIconProvider()
        pm = _icon_provider.icon(info).pixmap(QSize(64, 64))
    _icon_cache[path] = pm
    return pm


class ShortcutsWidget(Renderer):
    type_id, title, glyph = "shortcuts", "Atalhos para aplicativos", G.APPS
    description = "Ícones que abrem seus programas, pastas ou sites favoritos."
    default_refresh = 10_000
    defaults = {"items": [], "columns": 4}

    @property
    def base_size(self):  # cresce conforme a quantidade de atalhos
        cols = max(2, min(8, int(self.opt.get("columns", 4))))
        n = max(1, len(self.opt.get("items", [])))
        rows = min(4, math.ceil(n / cols))
        return (cols * 66 + 16, rows * 74 + 14)

    def _cells(self):
        cols = max(2, min(8, int(self.opt.get("columns", 4))))
        for i, it in enumerate(self.opt.get("items", [])[: cols * 4]):
            r, col = divmod(i, cols)
            yield QRectF(8 + col * 66, 8 + r * 74, 66, 74), it, i

    def draw(self, c: Canvas) -> None:
        items = self.opt.get("items", [])
        if not items:
            _no_data(c, "Botão direito → Configurar\npara adicionar atalhos")
            return
        for rect, it, _i in self._cells():
            pm = _icon_for(it.get("path", "")) if not it.get("path", "").startswith("http") else None
            ir = QRectF(rect.center().x() - 20, rect.y() + 6, 40, 40)
            if pm is not None and not pm.isNull():
                c.p.drawPixmap(ir, pm, QRectF(pm.rect()))
            else:
                c.rounded(ir.x(), ir.y(), 40, 40, 10, c.s.faint)
                c.glyph(ir.x(), ir.y(), 40, 40, "" if it.get("path", "").startswith("http") else G.APPS, 16)
            c.text(rect.x() + 2, rect.y() + 48, rect.width() - 4, 22, it.get("name", "")[:14], 10,
                   align=Qt.AlignHCenter | Qt.AlignTop)

    def hit_areas(self):
        return [(rect, str(i)) for rect, _it, i in self._cells()]

    def on_click(self, area_id: str) -> None:
        items = self.opt.get("items", [])
        i = int(area_id)
        if 0 <= i < len(items):
            path = items[i].get("path", "")
            if path.startswith("http") or os.path.exists(path):
                shell_open(path, items[i].get("args", ""))

    def tooltip(self) -> str:
        return ""


# ================================================================ 15. Monitor de processos
class ProcessWidget(Renderer):
    type_id, title, glyph = "processes", "Monitor de processos", G.PROCESS
    description = "Os 5 aplicativos que mais usam CPU ou memória agora."
    base_size = (262, 168)
    default_refresh = 2000
    defaults = {"sort": "cpu"}

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s or not s.processes.apps:
            _no_data(c)
            return
        by_cpu = self.opt["sort"] == "cpu"
        apps = sorted(s.processes.apps, key=lambda a: a.cpu if by_cpu else a.memory, reverse=True)[:5]
        c.glyph(12, 8, 22, 22, G.PROCESS, 12)
        c.text(36, 8, 220, 22, "Processos · " + ("CPU" if by_cpu else "Memória"), 12.5, 600)
        top = max((a.cpu if by_cpu else a.memory) for a in apps) or 1
        for i, a in enumerate(apps):
            y = 36 + i * 26
            val = a.cpu if by_cpu else a.memory
            c.text(14, y, 150, 16, a.name.replace(".exe", "")[:20], 11.5)
            c.text(160, y, 88, 16, f"{a.cpu:.1f}%".replace(".", ",") if by_cpu else fmt_bytes(a.memory), 11, 600,
                   align=Qt.AlignRight | Qt.AlignVCenter)
            c.bar(14, y + 17, 234, 3.5, (val / top * 100) if by_cpu and top < 100 else (val / top * 100))


# ================================================================ 16. Visualizador de áudio
class VisualizerWidget(Renderer):
    type_id, title, glyph = "visualizer", "Visualizador de áudio", ""
    description = "Barras que dançam com o som que está tocando no PC."
    base_size = (320, 110)
    default_refresh = 33
    min_refresh = 33
    defaults = {"style": "bars", "bands": 32}

    def draw(self, c: Canvas) -> None:
        from ..media.visualizer import AudioVisualizer
        bands, peaks, _level = AudioVisualizer.instance().snapshot()
        n = max(8, min(48, int(self.opt["bands"])))
        step = len(bands) / n
        vals = [max(bands[int(i * step):int((i + 1) * step)] or [0]) for i in range(n)]
        pk = [max(peaks[int(i * step):int((i + 1) * step)] or [0]) for i in range(n)]
        x0, y0, w, h = 12, 10, c.w - 24, c.h - 20
        gap = 3
        bw = (w - gap * (n - 1)) / n
        mirror = self.opt["style"] == "mirror"
        from PySide6.QtGui import QLinearGradient, QBrush
        grad = QLinearGradient(0, y0 + h, 0, y0)
        grad.setColorAt(0, c.s.accent)
        grad.setColorAt(1, c.s.accent2)
        c.p.setPen(Qt.NoPen)
        c.p.setBrush(QBrush(grad))
        for i, v in enumerate(vals):
            bh = max(2.0, v * (h / 2 if mirror else h))
            x = x0 + i * (bw + gap)
            if mirror:
                c.p.drawRoundedRect(QRectF(x, y0 + h / 2 - bh, bw, bh * 2), bw / 2.5, bw / 2.5)
            else:
                c.p.drawRoundedRect(QRectF(x, y0 + h - bh, bw, bh), bw / 2.5, bw / 2.5)
                py = y0 + h - max(2.0, pk[i] * h) - 3
                c.rounded(x, py, bw, 2, 1, c.s.muted)


# ===================================================================== 17. Volume
class VolumeWidget(Renderer):
    type_id, title, glyph = "volume", "Volume e mixer", ""
    description = "Volume geral e dos apps que estão tocando, com controles."
    base_size = (280, 150)
    defaults = {"apps": 3}

    def draw(self, c: Canvas) -> None:
        from ..media import audio
        st = audio.cached()
        if st["error"]:
            _no_data(c, "Sem dispositivo de áudio")
            return
        vol, muted = st["master"]
        c.ring(46, 48, 30, 0 if muted else vol * 100, 7, RED if muted else None)
        c.text(16, 30, 60, 36, "mudo" if muted else f"{vol * 100:.0f}", 13 if muted else 19, 600, align=Qt.AlignCenter)
        c.text(96, 10, 170, 18, "Volume", 12.5, 600)
        for rect, aid in self.hit_areas():
            g = {"down": "", "mute": "" if muted else "", "up": ""}[aid]   # − / som / +
            c.rounded(rect.x(), rect.y(), rect.width(), rect.height(), 8, c.s.faint)
            c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 11, c.s.text)
        apps = [a for a in st["apps"] if a.key != "#system"][: int(self.opt["apps"])]
        if not apps:
            c.text(16, 96, 250, 20, "Nenhum app tocando som agora", 10.5, color=c.s.muted)
        for i, a in enumerate(apps[:3]):
            y = 92 + i * 18
            c.text(16, y - 1, 110, 16, a.name, 10.5, color=c.s.muted if a.muted else c.s.text)
            c.bar(130, y + 5, 100, 4, 0 if a.muted else a.volume * 100)
            c.bar(236, y + 5, 30, 4, min(100, a.peak * 140), GREEN)

    def hit_areas(self):
        return [(QRectF(96, 40, 50, 30), "down"), (QRectF(152, 40, 50, 30), "mute"),
                (QRectF(208, 40, 58, 30), "up")]

    def on_click(self, area_id: str) -> None:
        from ..media import audio
        if area_id == "mute":
            _v, m = audio.master_volume()
            audio.set_master_mute(not m)
        else:
            audio.change_master_volume(0.05 if area_id == "up" else -0.05)
        audio.cached(max_age=0)


# ======================================================================== 18. OBS
class ObsWidget(Renderer):
    type_id, title, glyph = "obs", "OBS Studio", ""
    description = "Ao vivo/gravando, tempo, cena atual e bitrate, com botão de gravar."
    base_size = (280, 128)
    default_refresh = 1000

    def draw(self, c: Canvas) -> None:
        from ..media.obs import ObsClient
        st = ObsClient.instance().status
        c.glyph(12, 8, 22, 22, "", 12)
        c.text(36, 8, 160, 22, "OBS Studio", 12.5, 600)
        if st.state != "connected":
            c.text(14, 42, 252, 20, "Desconectado" if st.state != "connecting" else "Conectando...", 14, 600,
                   color=c.s.muted)
            c.text(14, 64, 252, 34, "Ative em Mídia → OBS no PC Control Center", 10.5, color=c.s.muted)
            return
        live_c = RED if st.streaming else c.s.faint
        c.rounded(14, 38, 112, 30, 8, live_c)
        c.text(14, 38, 112, 30, f"AO VIVO {st.stream_time}" if st.streaming else "Offline", 11.5, 700,
               QColor("white") if st.streaming else c.s.muted, align=Qt.AlignCenter)
        rec = self.hit_areas()[0][0]
        c.rounded(rec.x(), rec.y(), rec.width(), rec.height(), 8, RED if st.recording else c.s.faint)
        c.text(rec.x(), rec.y(), rec.width(), rec.height(),
               f"● REC {st.record_time}" if st.recording else "● Gravar", 11.5, 700,
               QColor("white") if st.recording else c.s.text, align=Qt.AlignCenter)
        c.text(14, 76, 252, 18, f"Cena: {st.scene or '—'}", 11.5)
        info = f"CPU do OBS {st.obs_cpu:.0f}%"
        if st.streaming:
            info = (f"{st.bitrate_kbps:.0f} kbps · perdidos {st.dropped_pct:.1f}%".replace(".", ",")
                    + " · " + info)
        c.text(14, 98, 252, 18, info, 10, color=c.s.muted)

    def hit_areas(self):
        return [(QRectF(134, 38, 132, 30), "record")]

    def on_click(self, area_id: str) -> None:
        from ..media.obs import ObsClient
        if area_id == "record":
            ObsClient.instance().toggle_record()


# ===================================================================== 19. YouTube
class YouTubeWidget(Renderer):
    type_id, title, glyph = "youtube", "YouTube: vídeos novos", ""
    description = "Último vídeo dos seus canais; clique para assistir, setas para os anteriores."
    base_size = (330, 132)
    default_refresh = 5000

    def __init__(self, cfg):
        super().__init__(cfg)
        self.index = 0
        self._img_key, self._img = "", None

    def _videos(self):
        from ..media.youtube import YouTubeFeed
        feed = YouTubeFeed.instance()
        return feed, feed.videos[:8]

    def draw(self, c: Canvas) -> None:
        from ..media.youtube import ago
        feed, vids = self._videos()
        if not vids:
            _no_data(c, "Adicione canais em Mídia → YouTube" if not feed.channels() else "Carregando vídeos...")
            return
        self.index %= len(vids)
        v = vids[self.index]
        if self._img_key != v.id:
            data = feed.thumb(v)
            self._img_key, self._img = v.id, QImage.fromData(data) if data else None
        art = QRectF(12, 12, 160, 90)
        path = QPainterPath()
        path.addRoundedRect(art, 10, 10)
        if self._img is not None and not self._img.isNull():
            c.p.save()
            c.p.setClipPath(path)
            c.p.drawImage(art, self._img)
            c.p.restore()
        else:
            c.rounded(art.x(), art.y(), art.width(), art.height(), 10, c.s.faint)
        c.text(182, 10, 138, 56, v.title, 11.5, 600, align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        c.text(182, 70, 138, 16, v.channel, 10, color=c.s.accent)
        c.text(182, 86, 138, 16, ago(v.published), 10, color=c.s.muted)
        c.text(12, 108, 160, 18, f"{self.index + 1} de {len(vids)}", 9.5, color=c.s.muted, align=Qt.AlignCenter)
        for rect, aid in self.hit_areas()[1:]:
            c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), "" if aid == "prev" else "", 11,
                    c.s.text)

    def hit_areas(self):
        return [(QRectF(12, 12, 160, 90), "open"), (QRectF(12, 106, 30, 22), "prev"), (QRectF(142, 106, 30, 22), "next")]

    def on_click(self, area_id: str) -> None:
        _feed, vids = self._videos()
        if not vids:
            return
        if area_id == "open":
            shell_open(vids[self.index % len(vids)].url)
        else:
            self.index = (self.index + (1 if area_id == "next" else -1)) % len(vids)


# ========================================================================= 20. FPS
class FpsWidget(Renderer):
    type_id, title, glyph = "fps", "Contador de FPS", ""
    description = "FPS do jogo em foco, 1% mínimo e gráfico. Use a camada 'Sempre visível'."
    base_size = (220, 112)
    default_refresh = 500

    def draw(self, c: Canvas) -> None:
        from ..media.fps import FpsMonitor
        game, st = FpsMonitor.instance().current()
        if not st.get("running"):
            c.glyph(12, 8, 22, 22, "", 12)
            c.text(36, 8, 170, 22, "FPS", 12.5, 600)
            msg = "Iniciando..." if st.get("starting") else (st.get("error") or "Ligue em Mídia → FPS")
            c.text(14, 36, 192, 64, msg, 10.5, color=c.s.muted, align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
            return
        if game is None:
            c.text(14, 10, 192, 30, "FPS", 12.5, 600)
            c.text(14, 40, 192, 40, "Abra um jogo...", 13, color=c.s.muted)
            return
        fps = game["fps"]
        col = GREEN if fps >= 55 else AMBER if fps >= 30 else RED
        c.text(12, 2, 120, 56, f"{fps:.0f}", 44, 700, col)
        c.text(120, 10, 90, 16, "FPS", 11, 600, color=c.s.muted, align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(110, 26, 100, 16, f"1% mín {game['low1']:.0f}", 10.5, align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(110, 42, 100, 16, f"{game['frame_ms']:.1f} ms".replace(".", ","), 10.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        c.spark(12, 62, 196, 30, game.get("history") or [], col, capacity=60)
        c.text(12, 92, 196, 16, game["name"].removesuffix(".exe"), 9.5, color=c.s.muted)


REGISTRY: dict[str, type[Renderer]] = {cls.type_id: cls for cls in (
    ClockWidget, CalendarWidget, WeatherWidget, CpuWidget, RamWidget, GpuWidget, TempWidget, WifiWidget,
    NetSpeedWidget, StorageWidget, MediaWidget, SysInfoWidget, BatteryWidget, ShortcutsWidget, ProcessWidget,
    VisualizerWidget, VolumeWidget, ObsWidget, YouTubeWidget, FpsWidget)}
