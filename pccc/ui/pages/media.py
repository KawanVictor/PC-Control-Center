"""Mídia e streaming: áudio (saída, mixer por app, visualizador), OBS, YouTube e contador de FPS."""
from __future__ import annotations

import time

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileIconProvider, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ...core.config import Settings
from ...core.secrets import protect, unprotect
from ...core.winapi import shell_open
from ...media import audio
from ...media import fps as fpsmod
from ...media import youtube as yt
from ...media.obs import ObsClient
from ...media.visualizer import AudioVisualizer
from ..components import GlassCard, ResponsiveGrid, Segmented, ToggleSwitch, label
from ..icons import G
from ..tasks import run_task
from ..theme import ThemeManager
from .apps import _ask
from .base import Page


def _row(title: str, desc: str, control: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 4, 0, 4)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(label(title))
    if desc:
        col.addWidget(label(desc, "Faint", wrap=True))
    h.addLayout(col, 1)
    h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
    return w


# =============================================================== componentes
def _mute_button() -> QPushButton:
    from PySide6.QtGui import QFont
    from ..theme import icon_font_family
    b = QPushButton()
    b.setCheckable(True)
    b.setFixedWidth(44)
    f = QFont(icon_font_family())
    f.setPixelSize(15)
    b.setFont(f)
    _mute_glyph(b, False)
    return b


def _mute_glyph(b: QPushButton, muted: bool) -> None:
    b.setText("" if muted else "")       # alto-falante cortado / alto-falante
    b.setToolTip("Ativar o som" if muted else "Silenciar")


class LevelMeter(QWidget):
    """Barrinha do nível de som (0–1)."""

    def __init__(self) -> None:
        super().__init__()
        self.value = 0.0
        self.setFixedSize(70, 8)

    def set_value(self, v: float) -> None:
        if abs(v - self.value) > 0.01:
            self.value = v
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(self.rect()), 4, 4)
        w = self.width() * max(0.0, min(1.0, self.value * 1.4))
        if w > 1:
            p.setBrush(QColor("#34d399") if self.value < 0.7 else QColor("#fbbf24"))
            p.drawRoundedRect(QRectF(0, 0, w, self.height()), 4, 4)
        p.end()


class SpectrumView(QWidget):
    """Visualizador grande (30 quadros/s enquanto visível)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(170)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._timer.start(33)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def paintEvent(self, _e) -> None:
        bands, peaks, _lvl = AudioVisualizer.instance().snapshot()
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(bands)
        gap = 4
        bw = (w - gap * (n - 1)) / n
        g = QLinearGradient(0, h, 0, 0)
        g.setColorAt(0, QColor(t.accent))
        g.setColorAt(1, QColor(t.accent2))
        p.setPen(Qt.NoPen)
        for i, v in enumerate(bands):
            x = i * (bw + gap)
            bh = max(3.0, v * (h - 8))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x, h - bh, bw, bh), bw / 3, bw / 3)
            py = h - max(3.0, peaks[i] * (h - 8)) - 5
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawRoundedRect(QRectF(x, py, bw, 2.5), 1, 1)
        p.end()


class Sparkline(QWidget):
    def __init__(self, height: int = 90) -> None:
        super().__init__()
        self.values: list[float] = []
        self.setMinimumHeight(height)

    def set_values(self, vals: list[float]) -> None:
        self.values = list(vals)
        self.update()

    def paintEvent(self, _e) -> None:
        if len(self.values) < 2:
            return
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top = max(max(self.values) * 1.15, 30)
        step = w / 59
        x0 = w - step * (len(self.values) - 1)
        path = QPainterPath()
        for i, v in enumerate(self.values):
            pt = (x0 + i * step, h - h * min(1.0, v / top))
            path.moveTo(*pt) if i == 0 else path.lineTo(*pt)
        p.setPen(QPen(QColor(t.accent), 2))
        p.drawPath(path)
        p.setPen(QColor(t.p["muted"]))
        p.drawText(4, 14, f"{top:.0f}")
        p.end()


# ===================================================================== ÁUDIO
class AppRow(QWidget):
    def __init__(self, app: audio.AppAudio) -> None:
        super().__init__()
        self.key = app.key
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 3, 0, 3)
        h.setSpacing(10)
        ic = QLabel()
        ic.setFixedSize(22, 22)
        if app.exe:
            ic.setPixmap(QFileIconProvider().icon(QFileInfo(app.exe)).pixmap(QSize(20, 20)))
        h.addWidget(ic)
        self.name = label(app.name)
        self.name.setMinimumWidth(150)
        h.addWidget(self.name, 1)
        self.meter = LevelMeter()
        h.addWidget(self.meter)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(200)
        self.slider.valueChanged.connect(lambda v: audio.set_app_volume(self.key, v / 100))
        h.addWidget(self.slider)
        self.pct = label("", "Muted")
        self.pct.setFixedWidth(40)
        h.addWidget(self.pct)
        self.mute = _mute_button()
        self.mute.setToolTip("Silenciar este aplicativo")
        self.mute.toggled.connect(lambda on: (audio.set_app_mute(self.key, on), self._mute_icon(on)))
        h.addWidget(self.mute)
        self.update_from(app)

    def _mute_icon(self, on: bool) -> None:
        _mute_glyph(self.mute, on)

    def update_from(self, a: audio.AppAudio) -> None:
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(round(a.volume * 100))
            self.slider.blockSignals(False)
        self.pct.setText(f"{round(a.volume * 100)}%")
        self.mute.blockSignals(True)
        self.mute.setChecked(a.muted)
        self.mute.blockSignals(False)
        self._mute_icon(a.muted)
        self.meter.set_value(0 if a.muted else a.peak)
        self.name.setObjectName("Muted" if not a.active else "")


class AudioView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)

        out = GlassCard("Saída de som", G.VOLUME)
        out.add(label("Para onde vai o som do PC. A troca vale para jogos, música, chamadas e sons do sistema.",
                      "Faint", wrap=True))
        self.dev_box = QVBoxLayout()
        self.dev_box.setSpacing(6)
        out.add(self.dev_box)
        mv = QHBoxLayout()
        mv.addWidget(label("Volume geral"))
        self.master = QSlider(Qt.Horizontal)
        self.master.setRange(0, 100)
        self.master.valueChanged.connect(self._set_master)
        mv.addWidget(self.master, 1)
        self.master_pct = label("", "Value")
        self.master_pct.setFixedWidth(48)
        mv.addWidget(self.master_pct)
        self.master_mute = _mute_button()
        self.master_mute.toggled.connect(lambda on: (audio.set_master_mute(on), _mute_glyph(self.master_mute, on)))
        mv.addWidget(self.master_mute)
        out.add(mv)
        out.add(QWidget(), 1)          # empurra o conteúdo para cima quando o cartão vizinho é mais alto
        grid.add(out)

        vis = GlassCard("Visualizador", G.MEDIA)
        vis.add(label("O som que está tocando agora, em tempo real (nada é gravado).", "Faint", wrap=True))
        self.spectrum = SpectrumView()
        vis.add(self.spectrum)
        add_w = QPushButton("Colocar o visualizador na área de trabalho")
        add_w.clicked.connect(lambda: _add_widget("visualizer"))
        vis.add(add_w)
        grid.add(vis)
        lay.addWidget(grid)

        mix = GlassCard("Volume por aplicativo", G.APPS)
        mix.add(label("Cada programa com som tem seu próprio volume — igual ao Mixer de Volume do Windows. "
                      "Apps em cinza estão abertos mas em silêncio agora.", "Faint", wrap=True))
        self.apps_box = QVBoxLayout()
        self.apps_box.setSpacing(2)
        mix.add(self.apps_box)
        self.apps_empty = label("Nenhum aplicativo está usando o som agora.", "Muted")
        mix.add(self.apps_empty)
        add_v = QPushButton("Colocar o mixer na área de trabalho")
        add_v.clicked.connect(lambda: _add_widget("volume"))
        mix.add(add_v, 0)
        lay.addWidget(mix)
        self.rows: dict[str, AppRow] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._dev_ids: list[str] = []

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh(devices=True)
        self._timer.start(700)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _set_master(self, v: int) -> None:
        audio.set_master_volume(v / 100)
        self.master_pct.setText(f"{v}%")

    def refresh(self, devices: bool = False) -> None:
        try:
            vol, muted = audio.master_volume()
            apps = audio.app_sessions()
        except Exception as e:     # noqa: BLE001
            self.apps_empty.setText(f"Sem dispositivo de áudio: {e}")
            self.apps_empty.show()
            return
        if not self.master.isSliderDown():
            self.master.blockSignals(True)
            self.master.setValue(round(vol * 100))
            self.master.blockSignals(False)
            self.master_pct.setText(f"{round(vol * 100)}%")
        self.master_mute.blockSignals(True)
        self.master_mute.setChecked(muted)
        _mute_glyph(self.master_mute, muted)
        self.master_mute.blockSignals(False)
        keys = [a.key for a in apps]
        if keys != list(self.rows):
            for r in self.rows.values():
                r.setParent(None)
                r.deleteLater()
            self.rows = {}
            for a in apps:
                row = AppRow(a)
                self.rows[a.key] = row
                self.apps_box.addWidget(row)
        else:
            for a in apps:
                self.rows[a.key].update_from(a)
        self.apps_empty.setVisible(not apps)
        if devices or int(time.time()) % 5 == 0:
            self._load_devices()

    def _load_devices(self) -> None:
        try:
            devs = audio.output_devices()
        except Exception:
            devs = []
        ids = [f"{d.id}{d.default}" for d in devs]
        if ids == self._dev_ids:
            return
        self._dev_ids = ids
        while self.dev_box.count():
            w = self.dev_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for d in devs:
            b = QPushButton(("✓  " if d.default else "     ") + d.name)
            b.setObjectName("Primary" if d.default else "")
            b.setStyleSheet("text-align: left; padding: 8px 12px;")
            b.clicked.connect(lambda _=False, dev=d: self._choose(dev))
            self.dev_box.addWidget(b)
        if not devs:
            self.dev_box.addWidget(label("Nenhuma saída de som ativa.", "Muted"))

    def _choose(self, d: audio.OutputDevice) -> None:
        if d.default:
            return
        try:
            audio.set_default_output(d.id)
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Saída de som", str(e))
        self._dev_ids = []
        self._load_devices()


def _add_widget(type_id: str, layer: str | None = None) -> None:
    from ...widgets.manager import WidgetManager
    wm = WidgetManager.instance()
    win = wm.add(type_id)
    if layer:
        win.cfg.layer = layer
        win.apply_layer()
        wm.save()


# ======================================================================= OBS
class ObsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.client = ObsClient.instance()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)

        con = GlassCard("Conexão com o OBS Studio", G.VIDEO)
        con.add(label("No OBS (versão 28 ou mais nova): Ferramentas → Configurações do servidor WebSocket → "
                      "marque “Ativar servidor WebSocket” e copie a senha em “Mostrar informações de conexão”.",
                      "Faint", wrap=True))
        self.enabled = ToggleSwitch()
        self.enabled.setChecked(bool(s.get("media.obs.enabled", False)))
        self.enabled.toggled.connect(self._toggle_enabled)
        con.add(_row("Integração com o OBS", "Conecta sozinho quando o OBS estiver aberto", self.enabled))
        hp = QHBoxLayout()
        self.host = QLineEdit(s.get("media.obs.host", "127.0.0.1"))
        self.host.setPlaceholderText("127.0.0.1")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(s.get("media.obs.port", 4455)))
        hp.addWidget(label("Endereço"))
        hp.addWidget(self.host, 1)
        hp.addWidget(label("Porta"))
        hp.addWidget(self.port)
        con.add(hp)
        pw = QHBoxLayout()
        self.password = QLineEdit(unprotect(s.get("media.obs.password", "")))
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Senha do servidor WebSocket (se houver)")
        pw.addWidget(label("Senha"))
        pw.addWidget(self.password, 1)
        con.add(pw)
        btns = QHBoxLayout()
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(self._connect)
        btns.addWidget(self.connect_btn)
        btns.addStretch(1)
        con.add(btns)
        self.state_lbl = label("", "Muted", wrap=True)
        con.add(self.state_lbl)
        con.add(label("A senha fica guardada criptografada pelo Windows (só a sua conta consegue ler).", "Faint",
                      wrap=True))
        grid.add(con)

        st = GlassCard("Transmissão e gravação", G.VIDEO)
        self.live_lbl = label("Offline", "Value")
        st.add(self.live_lbl)
        self.stats_lbl = label("", "Muted", wrap=True)
        st.add(self.stats_lbl)
        b2 = QHBoxLayout()
        self.stream_btn = QPushButton("Iniciar transmissão")
        self.stream_btn.clicked.connect(self._toggle_stream)
        self.rec_btn = QPushButton("Iniciar gravação")
        self.rec_btn.clicked.connect(self.client.toggle_record)
        b2.addWidget(self.stream_btn)
        b2.addWidget(self.rec_btn)
        st.add(b2)
        addw = QPushButton("Colocar o painel do OBS na área de trabalho")
        addw.clicked.connect(lambda: _add_widget("obs"))
        st.add(addw)
        grid.add(st)
        lay.addWidget(grid)

        self.scenes_card = GlassCard("Cenas — clique para trocar", G.SCENES)
        self.scenes_grid = ResponsiveGrid(min_col_width=180, max_cols=5, spacing=8)
        self.scenes_card.add(self.scenes_grid)
        lay.addWidget(self.scenes_card)
        self.client.status_changed.connect(self._update)
        self._update(self.client.status)

    def _save(self) -> None:
        s = Settings.instance()
        s.set("media.obs.host", self.host.text().strip() or "127.0.0.1", save=False)
        s.set("media.obs.port", self.port.value(), save=False)
        s.set("media.obs.password", protect(self.password.text()), save=False)
        s.save()

    def _toggle_enabled(self, on: bool) -> None:
        Settings.instance().set("media.obs.enabled", on)
        if on:
            self._connect()
        else:
            self.client.disconnect_obs()

    def _connect(self) -> None:
        if self.client.status.state == "connected":
            self.client.disconnect_obs()
            return
        self._save()
        if not self.enabled.isChecked():
            self.enabled.blockSignals(True)
            self.enabled.setChecked(True)
            self.enabled.blockSignals(False)
            Settings.instance().set("media.obs.enabled", True)
        self.client.connect_obs(self.host.text().strip() or "127.0.0.1", self.port.value(), self.password.text())

    def _toggle_stream(self) -> None:
        st = self.client.status
        if st.streaming:
            ok = _ask(self, "Encerrar transmissão", "Encerrar a transmissão ao vivo agora?",
                      "Quem estiver assistindo verá a live terminar.", "Encerrar")
        else:
            ok = _ask(self, "Iniciar transmissão", "Começar a transmitir ao vivo agora?",
                      "O OBS vai iniciar a transmissão com as configurações de saída dele.", "Transmitir")
        if ok:
            self.client.toggle_stream()

    def _update(self, st) -> None:
        names = {"disconnected": "Desconectado", "connecting": "Conectando...", "connected": f"Conectado ✓ "
                 f"(obs-websocket {st.version})", "error": "Erro"}
        self.state_lbl.setText(names.get(st.state, st.state) + (f" — {st.error}" if st.error else ""))
        self.connect_btn.setText("Desconectar" if st.state == "connected" else "Conectar")
        on = st.state == "connected"
        for b in (self.stream_btn, self.rec_btn):
            b.setEnabled(on)
        self.stream_btn.setText("Encerrar transmissão" if st.streaming else "Iniciar transmissão")
        self.stream_btn.setObjectName("Danger" if st.streaming else "Primary")
        self.stream_btn.style().polish(self.stream_btn)
        self.rec_btn.setText("Parar gravação" if st.recording else "Iniciar gravação")
        if not on:
            self.live_lbl.setText("OBS não conectado")
            self.stats_lbl.setText("")
        else:
            parts = []
            if st.streaming:
                parts.append(f"🔴 AO VIVO {st.stream_time}")
            if st.recording:
                parts.append(f"⏺ Gravando {st.record_time}" + (" (pausada)" if st.record_paused else ""))
            self.live_lbl.setText("  ·  ".join(parts) or "Offline (pronto)")
            info = [f"Cena: {st.scene or '—'}", f"CPU do OBS: {st.obs_cpu:.1f}%".replace(".", ","),
                    f"Quadros: {st.fps:.0f} fps"]
            if st.streaming:
                info += [f"Bitrate: {st.bitrate_kbps:.0f} kbps",
                         f"Quadros perdidos: {st.dropped_pct:.1f}%".replace(".", ",")]
            self.stats_lbl.setText("   ·   ".join(info))
        key = (tuple(st.scenes), st.scene, st.state)
        if key != getattr(self, "_scene_key", None):
            self._scene_key = key
            self._fill_scenes(st)

    def _fill_scenes(self, st) -> None:
        # recria os botões das cenas (poucos itens)
        self.scenes_grid.clear()
        self._scene_btns = []
        for name in st.scenes if st.state == "connected" else []:
            b = QPushButton(name)
            b.setObjectName("Primary" if name == st.scene else "")
            b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False, n=name: self.client.set_scene(n))
            self.scenes_grid.add(b)
            self._scene_btns.append(b)
        self.scenes_card.setVisible(bool(self._scene_btns))


# =================================================================== YOUTUBE
class VideoCard(QFrame):
    def __init__(self, v: yt.Video, thumb: bytes) -> None:
        super().__init__()
        self.setObjectName("VideoCard")
        self.setCursor(Qt.PointingHandCursor)
        self.url = v.url
        self.setToolTip(v.title)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        img = QLabel()
        img.setFixedHeight(124)
        img.setAlignment(Qt.AlignCenter)
        qi = QImage.fromData(thumb) if thumb else QImage()
        if not qi.isNull():
            img.setPixmap(QPixmap.fromImage(qi.scaled(220, 124, Qt.KeepAspectRatioByExpanding,
                                                      Qt.SmoothTransformation)))
        img.setStyleSheet("border-radius: 8px; background: rgba(255,255,255,0.05);")
        lay.addWidget(img)
        t = label(v.title, wrap=True)
        t.setMaximumHeight(40)
        lay.addWidget(t)
        lay.addWidget(label(f"{v.channel} · {yt.ago(v.published)}", "Faint"))
        if v.views:
            lay.addWidget(label(yt.fmt_views(v.views), "Faint"))

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            shell_open(self.url)


class YouTubeView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.feed = yt.YouTubeFeed.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        ch = GlassCard("Seus canais", G.VIDEO)
        ch.add(label("Cole o link do canal (ex.: youtube.com/@nome) ou só o @nome. Os vídeos vêm do feed público "
                     "do YouTube — sem login.", "Faint", wrap=True))
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("https://www.youtube.com/@canal")
        self.input.returnPressed.connect(self._add)
        self.add_btn = QPushButton("Adicionar canal")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.input, 1)
        row.addWidget(self.add_btn)
        ch.add(row)
        self.status = label("", "Muted", wrap=True)
        ch.add(self.status)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        ch.add(self.chips)
        opts = QHBoxLayout()
        self.notify = QCheckBox("Avisar quando sair vídeo novo")
        self.notify.setChecked(bool(Settings.instance().get("media.youtube.notify", True)))
        self.notify.toggled.connect(lambda v: Settings.instance().set("media.youtube.notify", v))
        opts.addWidget(self.notify)
        opts.addStretch(1)
        refresh = QPushButton("Atualizar agora")
        refresh.clicked.connect(self.feed.refresh)
        opts.addWidget(refresh)
        addw = QPushButton("Widget na área de trabalho")
        addw.clicked.connect(lambda: _add_widget("youtube"))
        opts.addWidget(addw)
        ch.add(opts)
        lay.addWidget(ch)

        vids = GlassCard("Vídeos mais recentes", G.VIDEO)
        self.grid = ResponsiveGrid(min_col_width=220, max_cols=5, spacing=12)
        vids.add(self.grid)
        self.empty = label("Adicione um canal para ver os vídeos novos aqui.", "Muted")
        vids.add(self.empty)
        lay.addWidget(vids)
        self.cards: list[VideoCard] = []
        self.feed.updated.connect(self._render)
        self._render()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.feed.channels() and time.time() - self.feed.last_update > 600:
            self.feed.refresh()

    def _add(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.add_btn.setEnabled(False)
        self.status.setText("Procurando o canal...")

        def done(res):
            cid, name = res
            s = Settings.instance()
            chans = [c for c in (s.get("media.youtube.channels") or []) if isinstance(c, dict)]
            if any(c.get("id") == cid for c in chans):
                self.status.setText(f"“{name}” já está na lista.")
            else:
                chans.append({"id": cid, "name": name})
                s.set("media.youtube.channels", chans)
                self.status.setText(f"✓ “{name}” adicionado.")
                self.feed.start()
                self.feed.refresh()
            self.input.clear()
            self.add_btn.setEnabled(True)
            self._render()

        def fail(msg):
            self.status.setText(msg)
            self.add_btn.setEnabled(True)

        run_task(yt.resolve_channel, text, on_done=done, on_error=fail)

    def _remove(self, cid: str) -> None:
        s = Settings.instance()
        s.set("media.youtube.channels", [c for c in (s.get("media.youtube.channels") or []) if c.get("id") != cid])
        self.feed.videos = [v for v in self.feed.videos if v.channel_id != cid]
        yt.save_cache(self.feed.videos)
        self._render()

    def _render(self) -> None:
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in self.feed.channels():
            b = QPushButton(f"{c.get('name', c['id'])}  ✕")
            b.setToolTip("Remover canal")
            b.clicked.connect(lambda _=False, cid=c["id"]: self._remove(cid))
            self.chips.addWidget(b)
        self.chips.addStretch(1)
        self.grid.clear()
        self.cards = []
        for v in self.feed.videos[:20]:
            card = VideoCard(v, self.feed.thumb(v))
            self.grid.add(card)
            self.cards.append(card)
        self.empty.setVisible(not self.cards)
        if self.feed.loading:
            self.empty.setText("Carregando vídeos...")
            self.empty.show()
        elif self.feed.errors:
            self.status.setText("Alguns canais não carregaram: " + "; ".join(self.feed.errors[:3]))
        page = self.window().findChild(Page, "MediaPage") if self.window() else None
        if page is not None:
            page.relayout()


# ======================================================================= FPS
class FpsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.mon = fpsmod.FpsMonitor.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)

        setup = GlassCard("Contador de FPS", G.GAME)
        setup.add(label("Mede os quadros por segundo de qualquer jogo (DirectX, Vulkan, OpenGL) com o PresentMon, "
                        "ferramenta oficial e gratuita da Intel. O Windows só libera essa medição para "
                        "administradores: ao ligar, aparece UM aviso do Windows (UAC) por sessão.",
                        "Faint", wrap=True))
        self.pm_status = label("", "Muted", wrap=True)
        setup.add(self.pm_status)
        b = QHBoxLayout()
        self.dl_btn = QPushButton("Baixar PresentMon (Intel, ~1 MB)")
        self.dl_btn.clicked.connect(self._download)
        self.start_btn = QPushButton("Ligar contador")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._toggle)
        b.addWidget(self.dl_btn)
        b.addWidget(self.start_btn)
        b.addStretch(1)
        setup.add(b)
        overlay = QPushButton("Mostrar FPS por cima do jogo (widget sempre visível)")
        overlay.clicked.connect(lambda: _add_widget("fps", layer="top"))
        setup.add(overlay)
        setup.add(label("O widget aparece sobre jogos em janela ou “tela cheia sem bordas”. Em tela cheia "
                        "exclusiva, nenhum programa externo consegue desenhar por cima.", "Faint", wrap=True))
        grid.add(setup)

        live = GlassCard("Agora", G.PERFORMANCE)
        self.game_lbl = label("—", "Muted")
        live.add(self.game_lbl)
        nums = QHBoxLayout()
        self.fps_lbl = QLabel("--")
        self.fps_lbl.setStyleSheet("font-size: 54px; font-weight: 700;")
        nums.addWidget(self.fps_lbl)
        col = QVBoxLayout()
        self.low_lbl = label("1% mínimo: —", "Value")
        self.ft_lbl = label("Tempo de quadro: —", "Muted")
        col.addWidget(self.low_lbl)
        col.addWidget(self.ft_lbl)
        nums.addLayout(col, 1)
        live.add(nums)
        self.spark = Sparkline()
        live.add(self.spark)
        self.others = label("", "Faint", wrap=True)
        live.add(self.others)
        grid.add(live)
        lay.addWidget(grid)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()
        self._timer.start(500)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _download(self) -> None:
        if not _ask(self, "Baixar PresentMon",
                    "Baixar o PresentMon do GitHub oficial da Intel?",
                    "Origem: github.com/GameTechDev/PresentMon (versão estável mais recente, ~1 MB).\n"
                    f"Destino: {fpsmod.presentmon_path()}\n\n"
                    "Antes de usar, o app confere a assinatura digital da Intel — se não for válida, o arquivo "
                    "é descartado.", "Baixar"):
            return
        self.dl_btn.setEnabled(False)
        self.pm_status.setText("Baixando...")
        run_task(fpsmod.download, on_done=lambda tag: (self.pm_status.setText(f"✓ PresentMon {tag} instalado e "
                                                                               "assinatura da Intel conferida."),
                                                        self.refresh()),
                 on_error=lambda m: (self.pm_status.setText(f"Falhou: {m}"), self.dl_btn.setEnabled(True)))

    def _toggle(self) -> None:
        if self.mon.running():
            self.mon.stop()
        else:
            try:
                if not self.mon.start():
                    self.pm_status.setText("O aviso do Windows (UAC) foi recusado — o contador não foi ligado.")
            except FileNotFoundError:
                QMessageBox.information(self, "Contador de FPS", "Baixe o PresentMon primeiro.")
        self.refresh()

    def refresh(self) -> None:
        ver = fpsmod.installed_version()
        has = fpsmod.presentmon_path().exists()
        self.dl_btn.setText("Atualizar PresentMon" if has else "Baixar PresentMon (Intel, ~1 MB)")
        self.dl_btn.setEnabled(True)
        game, st = self.mon.current()
        running = bool(st.get("running"))
        self.start_btn.setEnabled(has)
        self.start_btn.setText("Desligar contador" if running or st.get("starting") else "Ligar contador")
        if not self.pm_status.text() or self.pm_status.text().startswith(("PresentMon", "Contador")):
            if st.get("error"):
                self.pm_status.setText(f"Contador: {st['error']}")
            elif running:
                self.pm_status.setText("Contador ligado — abra um jogo.")
            elif st.get("starting"):
                self.pm_status.setText("Contador: iniciando (confirme o aviso do Windows)...")
            else:
                self.pm_status.setText(f"PresentMon {ver} instalado." if has else "PresentMon não instalado.")
        if game:
            col = "#34d399" if game["fps"] >= 55 else "#fbbf24" if game["fps"] >= 30 else "#fb7185"
            self.fps_lbl.setText(f"{game['fps']:.0f}")
            self.fps_lbl.setStyleSheet(f"font-size: 54px; font-weight: 700; color: {col};")
            self.game_lbl.setText(game["name"])
            self.low_lbl.setText(f"1% mínimo: {game['low1']:.0f} FPS")
            self.ft_lbl.setText(f"Tempo de quadro: {game['frame_ms']:.1f} ms".replace(".", ","))
            self.spark.set_values(game.get("history") or [])
        else:
            self.fps_lbl.setText("--")
            self.fps_lbl.setStyleSheet("font-size: 54px; font-weight: 700; color: rgba(148,163,184,0.5);")
            self.game_lbl.setText("Nenhum jogo detectado" if running else "Contador desligado")
        others = [p for p in st.get("procs") or [] if not game or p["pid"] != game["pid"]][:4]
        self.others.setText(("Outros apps desenhando: " + ", ".join(f"{p['name']} {p['fps']:.0f}" for p in others))
                            if others else "")


# ===================================================================== PÁGINA
class MediaPage(Page):
    title = "Mídia e streaming"
    subtitle = "Som de cada app, visualizador, OBS, vídeos novos do YouTube e contador de FPS"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaPage")
        self.tabs = Segmented([("audio", "Áudio"), ("obs", "OBS"), ("youtube", "YouTube"), ("fps", "FPS")])
        self.add(self.tabs)
        self.views = {"audio": AudioView(), "obs": ObsView(), "youtube": YouTubeView(), "fps": FpsView()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.tabs.changed.connect(self.switch)
        self.switch("audio")

    def switch(self, key: str) -> None:
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        self.relayout()

    def on_shown(self) -> None:
        self.relayout()
