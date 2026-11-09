"""Aba OBS: conexão pelo obs-websocket, cenas, gravação e transmissão."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ....core.config import Settings
from ....core.secrets import protect, unprotect
from ....media.obs import ObsClient
from ...components import GlassCard, ResponsiveGrid, ToggleSwitch, label
from ...icons import G
from ..common import ask
from ..common import add_desktop_widget, setting_row


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
        con.add(setting_row("Integração com o OBS", "Conecta sozinho quando o OBS estiver aberto", self.enabled))
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
        addw.clicked.connect(lambda: add_desktop_widget("obs"))
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
            ok = ask(self, "Encerrar transmissão", "Encerrar a transmissão ao vivo agora?",
                      "Quem estiver assistindo verá a live terminar.", "Encerrar")
        else:
            ok = ask(self, "Iniciar transmissão", "Começar a transmitir ao vivo agora?",
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
