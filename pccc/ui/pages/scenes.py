"""Cenários e estilo: cenários, tema automático, papel de parede vivo, tela, atalhos e exportar/importar."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QTime, QTimer
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTimeEdit, QVBoxLayout,
                               QWidget)

from ...core.config import Settings
from ...personalization import bundle, display, dynwall, hotkeys, power, scenes, sun, wallpaper
from ...personalization.autotheme import AutoTheme
from ...personalization.display import WarmFilter
from ...personalization.livewall import GIF_EXT, VIDEO_EXT, LiveWallpaper
from ..components import GlassCard, ResponsiveGrid, Segmented, ToggleSwitch, label
from ..icons import G
from ..tasks import run_task
from .common import ask as _ask
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


def _slider(value: int, on_release, lo: int = 0, hi: int = 100, width: int = 220) -> tuple[QWidget, QSlider]:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    s.setFixedWidth(width)
    lbl = label(f"{value}%", "Value")
    lbl.setFixedWidth(46)
    s.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
    s.sliderReleased.connect(lambda: on_release(s.value()))
    s.valueChanged.connect(lambda v: None if s.isSliderDown() else on_release(v))
    h.addWidget(s)
    h.addWidget(lbl)
    return w, s


# ============================================================== EDITOR
class SceneEditor(QDialog):
    """Edita um cenário: cada ação tem uma caixa "incluir" e o valor."""

    def __init__(self, scene: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Cenário — {scene.get('name', '')}")
        self.resize(640, 720)
        self.scene = dict(scene)
        self.actions = dict(scene.get("actions") or {})
        outer = QVBoxLayout(self)
        top = QFormLayout()
        self.name = QLineEdit(scene.get("name", ""))
        top.addRow("Nome", self.name)
        self.desc = QLineEdit(scene.get("description", ""))
        top.addRow("Descrição", self.desc)
        self.color = scene.get("color", "#22d3ee")
        self.color_btn = QPushButton(self.color)
        self.color_btn.clicked.connect(self._pick_color)
        self._paint_color()
        top.addRow("Cor", self.color_btn)
        outer.addLayout(top)
        outer.addWidget(label("Marque o que este cenário deve mudar. O que não estiver marcado fica como está.",
                              "Faint", wrap=True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.form = QGridLayout(body)
        self.form.setColumnStretch(1, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.rows: dict[str, tuple[QCheckBox, callable]] = {}
        self._build()
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Salvar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, "Cor do cenário")
        if c.isValid():
            self.color = c.name()
            self._paint_color()

    def _paint_color(self) -> None:
        self.color_btn.setText(self.color)
        self.color_btn.setStyleSheet(f"background: {self.color}; color: black; font-weight: 600;")

    def _add(self, key: str, widget: QWidget, getter, setter=None) -> None:
        r = self.form.rowCount()
        cb = QCheckBox(scenes.ACTION_LABELS[key])
        cb.setChecked(key in self.actions and self.actions[key] not in (None, ""))
        widget.setEnabled(cb.isChecked())
        cb.toggled.connect(widget.setEnabled)
        if setter is not None and key in self.actions:
            setter(self.actions[key])
        self.form.addWidget(cb, r, 0)
        self.form.addWidget(widget, r, 1)
        self.rows[key] = (cb, getter)

    @staticmethod
    def _combo(items: list[tuple], current=None) -> QComboBox:
        c = QComboBox()
        for v, t in items:
            c.addItem(t, v)
        if current is not None:
            c.setCurrentIndex(max(0, c.findData(current)))
        return c

    def _build(self) -> None:
        pw = self._combo([(k, v[1]) for k, v in power.OVERLAYS.items()], self.actions.get("power"))
        self._add("power", pw, pw.currentData)
        wm = self._combo([("dark", "Escuro"), ("light", "Claro")], self.actions.get("windows_mode"))
        self._add("windows_mode", wm, wm.currentData)

        acc_btn = QPushButton(self.actions.get("accent") or "#0078D4")
        acc_btn.setProperty("val", self.actions.get("accent") or "#0078D4")

        def pick_acc():
            c = QColorDialog.getColor(QColor(acc_btn.property("val")), self, "Cor de destaque")
            if c.isValid():
                acc_btn.setProperty("val", c.name().upper())
                acc_btn.setText(c.name().upper())
        acc_btn.clicked.connect(pick_acc)
        self._add("accent", acc_btn, lambda: acc_btn.property("val"))

        wp = QPushButton(os.path.basename(self.actions.get("wallpaper", "")) or "Escolher imagem...")
        wp.setProperty("val", self.actions.get("wallpaper", ""))

        def pick_wp():
            f, _ = QFileDialog.getOpenFileName(self, "Imagem", "", "Imagens (*.jpg *.jpeg *.png *.bmp *.webp)")
            if f:
                wp.setProperty("val", os.path.normpath(f))
                wp.setText(os.path.basename(f))
        wp.clicked.connect(pick_wp)
        self._add("wallpaper", wp, lambda: wp.property("val"))

        lw = self._combo([("on", "Ligar (usa o vídeo escolhido em Papel de parede vivo)"), ("off", "Desligar")],
                         self.actions.get("livewall"))
        self._add("livewall", lw, lw.currentData)

        from ...widgets.manager import WidgetManager
        prof = self._combo([(n, n) for n in WidgetManager.instance().profile_names()], self.actions.get("widgets_profile"))
        self._add("widgets_profile", prof, prof.currentData)
        wv = self._combo([(True, "Mostrar"), (False, "Ocultar")], self.actions.get("widgets_visible"))
        self._add("widgets_visible", wv, wv.currentData)

        try:
            from ...media import audio
            devs = [(d.id, d.name) for d in audio.output_devices()]
        except Exception:
            devs = []
        ad = self._combo(devs or [("", "Nenhum dispositivo")], self.actions.get("audio_device"))
        self._add("audio_device", ad, ad.currentData)
        for key, default in (("volume", 50), ("brightness", 70), ("warm", 50)):
            sp = QSpinBox()
            sp.setRange(0, 100)
            sp.setSuffix(" %")
            sp.setValue(int(self.actions.get(key, default) or default))
            self._add(key, sp, sp.value)
        mu = self._combo([(True, "Mudo"), (False, "Com som")], self.actions.get("mute"))
        self._add("mute", mu, mu.currentData)
        sa = self._combo([(True, "Sim (alertas viram só registro; críticos continuam)"), (False, "Não")],
                         self.actions.get("silence_alerts"))
        self._add("silence_alerts", sa, sa.currentData)
        from ...media.obs import ObsClient
        obs = QComboBox()
        obs.setEditable(True)
        obs.addItems(ObsClient.instance().status.scenes)
        obs.setCurrentText(self.actions.get("obs_scene", "") or "")
        self._add("obs_scene", obs, obs.currentText)
        fp = self._combo([(True, "Ligar (pede o UAC)"), (False, "Desligar")], self.actions.get("fps_counter"))
        self._add("fps_counter", fp, fp.currentData)
        la = QPlainTextEdit("\n".join(self.actions.get("launch", []) or []))
        la.setPlaceholderText("Um por linha: caminho de programa ou site (https://...)")
        la.setFixedHeight(80)
        self._add("launch", la, lambda: [x.strip() for x in la.toPlainText().splitlines() if x.strip()])

    def _save(self) -> None:
        acts = {}
        for key, (cb, getter) in self.rows.items():
            if cb.isChecked():
                v = getter()
                if v not in (None, "", []):
                    acts[key] = v
        self.scene.update(name=self.name.text().strip() or "Cenário", description=self.desc.text().strip(),
                          color=self.color, actions=acts)
        self.accept()


# ============================================================ CENÁRIOS
class ScenesView(QWidget):
    def __init__(self, page: "ScenesPage") -> None:
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.banner = GlassCard()
        bh = QHBoxLayout()
        self.banner_lbl = label("", "Value", wrap=True)
        bh.addWidget(self.banner_lbl, 1)
        off = QPushButton("Voltar ao normal")
        off.setObjectName("Primary")
        off.clicked.connect(self._deactivate)
        bh.addWidget(off)
        self.banner.add(bh)
        lay.addWidget(self.banner)
        lay.addWidget(label("Um cenário aplica várias configurações de uma vez. “Voltar ao normal” desfaz tudo e "
                            "devolve o PC ao estado de antes. Dá para ativar também por atalho de teclado "
                            "(aba Atalhos) e pela bandeja.", "Muted", wrap=True))
        self.grid = ResponsiveGrid(min_col_width=300, max_cols=4)
        lay.addWidget(self.grid)
        b = QHBoxLayout()
        new = QPushButton("+ Novo cenário")
        new.clicked.connect(self._new)
        reset = QPushButton("Restaurar cenários padrão")
        reset.clicked.connect(self._reset)
        b.addWidget(new)
        b.addWidget(reset)
        b.addStretch(1)
        lay.addLayout(b)
        self.render()

    def render(self) -> None:
        act = scenes.active()
        self.banner.setVisible(bool(act))
        if act:
            since = datetime.fromtimestamp(act.get("since", 0)).strftime("%H:%M")
            self.banner_lbl.setText(f"Cenário ativo: {act.get('name', '')}  (desde {since})")
        self.grid.clear()
        for sc in scenes.scenes():
            self.grid.add(self._card(sc, act.get("id") == sc.get("id")))
        self.page.relayout()

    def _card(self, sc: dict, is_active: bool) -> QWidget:
        card = GlassCard(sc.get("name", ""), sc.get("glyph", G.SCENES))
        card.setStyleSheet(f"QFrame#GlassCard {{ border: 2px solid {sc.get('color', '#22d3ee')}; }}"
                           if is_active else "")
        if sc.get("description"):
            card.add(label(sc["description"], "Muted", wrap=True))
        items = scenes.describe(sc)
        card.add(label("\n".join(f"• {t}" for t in items) if items else "Nenhuma ação — clique em Editar.",
                       "Faint", wrap=True))
        h = QHBoxLayout()
        go = QPushButton("Ativo ✓" if is_active else "Ativar")
        go.setObjectName("Primary")
        go.setEnabled(not is_active)
        go.setStyleSheet(f"QPushButton#Primary {{ background: {sc.get('color', '#22d3ee')}; color: black; }}")
        go.clicked.connect(lambda _=False, sid=sc["id"]: self._activate(sid))
        ed = QPushButton("Editar")
        ed.clicked.connect(lambda _=False, s=sc: self._edit(s))
        rm = QPushButton("Excluir")
        rm.clicked.connect(lambda _=False, s=sc: self._remove(s))
        h.addWidget(go)
        h.addWidget(ed)
        h.addWidget(rm)
        h.addStretch(1)
        card.add(h)
        return card

    def _activate(self, sid: str) -> None:
        errors = scenes.activate(sid)
        if errors:
            QMessageBox.warning(self, "Cenário", "O cenário foi ativado, mas alguns itens não puderam ser "
                                                 "aplicados:\n\n" + "\n".join(errors))
        self.render()

    def _deactivate(self) -> None:
        errors = scenes.deactivate()
        if errors:
            QMessageBox.warning(self, "Voltar ao normal", "Alguns itens não puderam ser restaurados:\n\n"
                                + "\n".join(errors))
        self.render()

    def _edit(self, sc: dict) -> None:
        dlg = SceneEditor(sc, self)
        if dlg.exec():
            scenes.upsert(dlg.scene)
            hotkeys.HotkeyManager.instance().apply()
            self.render()

    def _new(self) -> None:
        self._edit(scenes.new_scene("Novo cenário"))

    def _remove(self, sc: dict) -> None:
        if _ask(self, "Excluir cenário", f"Excluir o cenário “{sc['name']}”?",
                "Só a configuração do cenário é apagada; nada no Windows muda.", "Excluir"):
            if scenes.active().get("id") == sc["id"]:
                scenes.deactivate()
            scenes.remove(sc["id"])
            self.render()

    def _reset(self) -> None:
        if _ask(self, "Cenários padrão", "Restaurar os 4 cenários padrão?",
                "Cenários que você criou ou editou serão substituídos.", "Restaurar"):
            if scenes.active():
                scenes.deactivate()
            Settings.instance().set("scenes.list", [])
            self.render()


# ========================================================= TEMA AUTOMÁTICO
class AutoThemeView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        card = GlassCard("Tema automático", G.SUN)
        self.enabled = ToggleSwitch()
        self.enabled.setChecked(bool(s.get("autotheme.enabled")))
        self.enabled.toggled.connect(self._toggle)
        card.add(_row("Claro de dia, escuro à noite", "Ao ligar, o modo atual vai para o Histórico de "
                      "personalização (desfazer volta para ele).", self.enabled))
        self.mode = Segmented([("sun", "Pelo nascer/pôr do sol"), ("fixed", "Em horários fixos")],
                              s.get("autotheme.mode", "sun"))
        self.mode.changed.connect(self._set_mode)
        card.add(self.mode)
        loc = QHBoxLayout()
        self.loc_lbl = label("", "Muted")
        loc.addWidget(self.loc_lbl, 1)
        self.city = QLineEdit()
        self.city.setPlaceholderText("Mudar cidade (ex.: Recife)")
        self.city.returnPressed.connect(self._geocode)
        loc.addWidget(self.city)
        btn = QPushButton("Buscar")
        btn.clicked.connect(self._geocode)
        loc.addWidget(btn)
        self.loc_row = QWidget()
        self.loc_row.setLayout(loc)
        card.add(self.loc_row)
        times = QHBoxLayout()
        self.light_at = QTimeEdit(QTime.fromString(s.get("autotheme.light_at", "07:00"), "HH:mm"))
        self.dark_at = QTimeEdit(QTime.fromString(s.get("autotheme.dark_at", "19:00"), "HH:mm"))
        for te, key in ((self.light_at, "light_at"), (self.dark_at, "dark_at")):
            te.setDisplayFormat("HH:mm")
            te.timeChanged.connect(lambda t, k=key: (Settings.instance().set(f"autotheme.{k}", t.toString("HH:mm")),
                                                     AutoTheme.instance().start() if self.enabled.isChecked() else None,
                                                     self.refresh()))
        times.addWidget(label("Claro às"))
        times.addWidget(self.light_at)
        times.addSpacing(20)
        times.addWidget(label("Escuro às"))
        times.addWidget(self.dark_at)
        times.addStretch(1)
        self.times_row = QWidget()
        self.times_row.setLayout(times)
        card.add(self.times_row)
        for key, text in (("apps", "Mudar o modo dos aplicativos do Windows"),
                          ("system", "Mudar a barra de tarefas e o menu Iniciar"),
                          ("app_theme", "Mudar também o tema do PC Control Center")):
            cb = QCheckBox(text)
            cb.setChecked(bool(s.get(f"autotheme.{key}", True)))
            cb.toggled.connect(lambda v, k=key: Settings.instance().set(f"autotheme.{k}", v))
            card.add(cb)
        self.next_lbl = label("", "Value")
        card.add(self.next_lbl)
        lay.addWidget(card)
        self.refresh()

    def _toggle(self, on: bool) -> None:
        AutoTheme.instance().enable(on)
        self.refresh()

    def _set_mode(self, mode: str) -> None:
        Settings.instance().set("autotheme.mode", mode)
        if self.enabled.isChecked():
            AutoTheme.instance().start()
        self.refresh()

    def _geocode(self) -> None:
        from ...widgets import weather as wx
        name = self.city.text().strip()
        if not name:
            return
        self.loc_lbl.setText("Procurando...")

        def done(res):
            if not res:
                self.loc_lbl.setText("Cidade não encontrada.")
                return
            Settings.instance().set("location", res)
            self.city.clear()
            if self.enabled.isChecked():
                AutoTheme.instance().start()
            self.refresh()

        run_task(wx.geocode, name, on_done=done, on_error=lambda e: self.loc_lbl.setText(f"Sem conexão: {e}"))

    def refresh(self) -> None:
        mode = Settings.instance().get("autotheme.mode", "sun")
        self.loc_row.setVisible(mode == "sun")
        self.times_row.setVisible(mode == "fixed")
        loc = sun.location()
        rise, set_ = sun.sun_times(float(loc["lat"]), float(loc["lon"]))
        self.loc_lbl.setText(f"{loc.get('label', '')} — hoje o sol nasce às {rise:%H:%M} e se põe às {set_:%H:%M}"
                             if rise else f"{loc.get('label', '')}")
        kind, when = AutoTheme.next_change()
        if self.enabled.isChecked() and when:
            day = "hoje" if when.date() == datetime.now().date() else "amanhã"
            self.next_lbl.setText(f"Próxima troca: modo {kind} {day} às {when:%H:%M}")
        else:
            self.next_lbl.setText("Desligado")


# ===================================================== PAPEL DE PAREDE VIVO
class LiveWallView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        self.dyn = dynwall.DynamicWallpaper.instance()
        self.live = LiveWallpaper.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)

        d = GlassCard("Papel de parede dinâmico", G.IMAGE)
        self.dyn_on = ToggleSwitch()
        self.dyn_on.setChecked(bool(s.get("dynwall.enabled")))
        self.dyn_on.toggled.connect(self._dyn_toggle)
        d.add(_row("Trocar automaticamente", "Ao ligar, a imagem atual vai para o Histórico (desfazer volta "
                   "para ela).", self.dyn_on))
        self.dyn_mode = QComboBox()
        for k, t in dynwall.MODES.items():
            self.dyn_mode.addItem(t, k)
        self.dyn_mode.setCurrentIndex(max(0, self.dyn_mode.findData(s.get("dynwall.mode", "bing"))))
        self.dyn_mode.currentIndexChanged.connect(self._dyn_mode)
        d.add(_row("Fonte das imagens", "", self.dyn_mode))
        # pasta
        self.folder_box = QWidget()
        fb = QVBoxLayout(self.folder_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fr = QHBoxLayout()
        self.folder_lbl = label(s.get("dynwall.folder", "") or "Nenhuma pasta escolhida", "Muted")
        fr.addWidget(self.folder_lbl, 1)
        pick = QPushButton("Escolher pasta...")
        pick.clicked.connect(self._pick_folder)
        fr.addWidget(pick)
        fb.addLayout(fr)
        ir = QHBoxLayout()
        ir.addWidget(label("Trocar a cada"))
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(" min")
        self.interval.setValue(int(s.get("dynwall.interval_min", 30)))
        self.interval.valueChanged.connect(lambda v: Settings.instance().set("dynwall.interval_min", v))
        ir.addWidget(self.interval)
        shuffle = QCheckBox("Ordem aleatória")
        shuffle.setChecked(bool(s.get("dynwall.shuffle", True)))
        shuffle.toggled.connect(lambda v: Settings.instance().set("dynwall.shuffle", v))
        ir.addWidget(shuffle)
        ir.addStretch(1)
        fb.addLayout(ir)
        d.add(self.folder_box)
        # períodos
        self.period_box = QWidget()
        pb = QFormLayout(self.period_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.period_btns = {}
        for key, text, _h in dynwall.PERIODS:
            b = QPushButton(os.path.basename((s.get("dynwall.periods") or {}).get(key, "")) or "Escolher imagem...")
            b.clicked.connect(lambda _=False, k=key: self._pick_period(k))
            self.period_btns[key] = b
            pb.addRow(text, b)
        d.add(self.period_box)
        st = QComboBox()
        for k, t in wallpaper.STYLE_LABELS.items():
            st.addItem(t, k)
        st.setCurrentIndex(max(0, st.findData(s.get("dynwall.style", "fill"))))
        st.currentIndexChanged.connect(lambda _i: Settings.instance().set("dynwall.style", st.currentData()))
        d.add(_row("Ajuste da imagem", "", st))
        nb = QHBoxLayout()
        nxt = QPushButton("Trocar agora")
        nxt.clicked.connect(self.dyn.next_now)
        nb.addWidget(nxt)
        opn = QPushButton("Abrir pasta das imagens baixadas")
        opn.clicked.connect(lambda: os.startfile(dynwall.daily_dir()))
        nb.addWidget(opn)
        nb.addStretch(1)
        d.add(nb)
        self.dyn_status = label("", "Muted", wrap=True)
        d.add(self.dyn_status)
        grid.add(d)

        lv = GlassCard("Papel de parede animado", G.VIDEO)
        lv.add(label("Um vídeo ou GIF toca atrás dos ícones da área de trabalho, sem som. Pausa sozinho em jogos "
                     "e vídeos em tela cheia para não pesar.", "Faint", wrap=True))
        self.live_on = ToggleSwitch()
        self.live_on.setChecked(self.live.running)
        self.live_on.toggled.connect(self._live_toggle)
        lv.add(_row("Ligado", "", self.live_on))
        fr2 = QHBoxLayout()
        self.video_lbl = label(os.path.basename(s.get("livewall.path", "")) or "Nenhum vídeo escolhido", "Muted")
        fr2.addWidget(self.video_lbl, 1)
        pv = QPushButton("Escolher vídeo ou GIF...")
        pv.clicked.connect(self._pick_video)
        fr2.addWidget(pv)
        lv.add(fr2)
        for key, text, default in (("all_screens", "Em todos os monitores", True),
                                   ("pause_when_covered", "Pausar quando uma janela maximizada cobrir a tela", True),
                                   ("pause_on_battery", "Pausar quando estiver na bateria", True)):
            cb = QCheckBox(text)
            cb.setChecked(bool(s.get(f"livewall.{key}", default)))
            cb.toggled.connect(lambda v, k=key: self._live_opt(k, v))
            lv.add(cb)
        self.live_status = label("", "Muted")
        lv.add(self.live_status)
        grid.add(lv)
        lay.addWidget(grid)

        self.dyn.changed.connect(lambda _p, cap: self.dyn_status.setText(f"✓ {cap}"))
        self.dyn.failed.connect(lambda m: self.dyn_status.setText(f"⚠ {m}"))
        self.live.state_changed.connect(self._live_state)
        self._dyn_mode_visibility()
        self._live_state("playing" if self.live.running else "stopped")

    # dinâmico
    def _dyn_toggle(self, on: bool) -> None:
        self.dyn.enable(on)
        self.dyn_status.setText("Buscando a imagem..." if on else "Desligado")

    def _dyn_mode(self, _i) -> None:
        Settings.instance().set("dynwall.mode", self.dyn_mode.currentData())
        self._dyn_mode_visibility()
        if self.dyn_on.isChecked():
            self.dyn.next_now()

    def _dyn_mode_visibility(self) -> None:
        m = self.dyn_mode.currentData()
        self.folder_box.setVisible(m == "folder")
        self.period_box.setVisible(m == "timeofday")

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta com imagens")
        if d:
            n = len(dynwall.folder_images(d))
            Settings.instance().set("dynwall.folder", os.path.normpath(d))
            self.folder_lbl.setText(f"{os.path.normpath(d)}  ({n} imagens)")

    def _pick_period(self, key: str) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Imagem", "", "Imagens (*.jpg *.jpeg *.png *.bmp *.webp)")
        if f:
            s = Settings.instance()
            per = dict(s.get("dynwall.periods") or {})
            per[key] = os.path.normpath(f)
            s.set("dynwall.periods", per)
            self.period_btns[key].setText(os.path.basename(f))

    # animado
    def _pick_video(self) -> None:
        exts = " ".join(f"*{e}" for e in VIDEO_EXT + GIF_EXT)
        f, _ = QFileDialog.getOpenFileName(self, "Vídeo ou GIF", "", f"Vídeos e GIFs ({exts})")
        if f:
            Settings.instance().set("livewall.path", os.path.normpath(f))
            self.video_lbl.setText(os.path.basename(f))
            if self.live.running:
                self._start_live()

    def _live_opt(self, key: str, value: bool) -> None:
        Settings.instance().set(f"livewall.{key}", value)
        if key == "all_screens" and self.live.running:
            self._start_live()

    def _start_live(self) -> bool:
        try:
            self.live.start()
            Settings.instance().set("livewall.enabled", True)
            return True
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Papel de parede animado", str(e))
            return False

    def _live_toggle(self, on: bool) -> None:
        if on:
            if not self._start_live():
                self.live_on.blockSignals(True)
                self.live_on.setChecked(False)
                self.live_on.blockSignals(False)
        else:
            self.live.stop()
            Settings.instance().set("livewall.enabled", False)

    def _live_state(self, st: str) -> None:
        text = {"playing": "▶ Tocando", "stopped": "Desligado"}.get(st, "")
        if st.startswith("paused"):
            text = f"⏸ Pausado ({st.split(':', 1)[1].strip()})"
        self.live_status.setText(text)
        self.live_on.blockSignals(True)
        self.live_on.setChecked(self.live.running)
        self.live_on.blockSignals(False)


# ================================================================ TELA
class DisplayView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)
        self.bright = GlassCard("Brilho", G.BRIGHTNESS)
        self.bright_box = QVBoxLayout()
        self.bright.add(self.bright_box)
        self.bright.add(label("Monitores externos só aceitam se o DDC/CI estiver ligado no menu do próprio monitor.",
                              "Faint", wrap=True))
        grid.add(self.bright)

        warm = GlassCard("Luz quente", G.MOON)
        warm.add(label("Deixa a tela mais amarelada para cansar menos a vista à noite. Se o app fechar, a tela "
                       "volta ao normal na hora. Se você usa a “Luz noturna” do Windows, prefira uma das duas.",
                       "Faint", wrap=True))
        w, self.warm_slider = _slider(WarmFilter.instance().level, self._set_warm)
        warm.add(_row("Intensidade agora", "0% = desligado", w))
        self.warm_auto = ToggleSwitch()
        self.warm_auto.setChecked(bool(s.get("display.warm_auto")))
        self.warm_auto.toggled.connect(self._toggle_auto)
        warm.add(_row("Ligar sozinho ao anoitecer", "Usa o nascer/pôr do sol do local do tema automático",
                      self.warm_auto))
        w2, self.warm_level = _slider(int(s.get("display.warm_level", 50)),
                                      lambda v: Settings.instance().set("display.warm_level", v))
        warm.add(_row("Intensidade à noite", "", w2))
        self.warm_status = label("", "Muted")
        warm.add(self.warm_status)
        grid.add(warm)
        lay.addWidget(grid)
        self._loaded = False

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            run_task(display.displays, on_done=self._fill)
        self.warm_slider.blockSignals(True)
        self.warm_slider.setValue(WarmFilter.instance().level)
        self.warm_slider.blockSignals(False)

    def _fill(self, ds) -> None:
        if not ds:
            self.bright_box.addWidget(label("Nenhuma tela com controle de brilho encontrada.", "Muted"))
            return
        for d in ds:
            w, _s = _slider(d.brightness, lambda v, did=d.id: self._set_bright(did, v))
            self.bright_box.addWidget(_row(d.name, d.kind, w))

    def _set_bright(self, did: str, v: int) -> None:
        try:
            display.set_brightness(did, v)
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Brilho", str(e))

    def _set_warm(self, v: int) -> None:
        try:
            WarmFilter.instance().set_level(v)
            self.warm_status.setText("" if v else "Desligado")
        except Exception as e:     # noqa: BLE001
            self.warm_status.setText(str(e))

    def _toggle_auto(self, on: bool) -> None:
        Settings.instance().set("display.warm_auto", on)
        AutoTheme.instance().warm_tick(force=True)
        self.warm_slider.setValue(WarmFilter.instance().level)


# ============================================================== ATALHOS
class HotkeysView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        card = GlassCard("Atalhos de teclado globais", G.KEYBOARD)
        en = ToggleSwitch()
        en.setChecked(bool(Settings.instance().get("hotkeys.enabled", True)))
        en.toggled.connect(lambda v: (Settings.instance().set("hotkeys.enabled", v),
                                      hotkeys.HotkeyManager.instance().apply(), self.render()))
        card.add(_row("Atalhos ligados", "Funcionam em qualquer programa, mesmo com o app na bandeja. Clique na "
                      "caixa e pressione a combinação (ex.: Ctrl+Alt+J).", en))
        self.form = QGridLayout()
        self.form.setColumnStretch(0, 1)
        card.add(self.form)
        lay.addWidget(card)
        self.render()

    def render(self) -> None:
        while self.form.count():
            w = self.form.takeAt(0).widget()
            if w:
                w.deleteLater()
        mgr = hotkeys.HotkeyManager.instance()
        b = hotkeys.bindings()
        for r, (action, text) in enumerate(hotkeys.actions().items()):
            self.form.addWidget(label(text), r, 0)
            ed = QKeySequenceEdit(QKeySequence(b.get(action, "")))
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)
            inner = ed.findChild(QLineEdit)
            if inner is not None:
                inner.setPlaceholderText("Pressione as teclas")
            ed.setFixedWidth(170)
            ed.editingFinished.connect(lambda a=action, e=ed: self._set(a, e))
            self.form.addWidget(ed, r, 1)
            clr = QPushButton("Limpar")
            clr.clicked.connect(lambda _=False, a=action: self._clear(a))
            self.form.addWidget(clr, r, 2)
            err = mgr.errors.get(action, "")
            st = label(f"⚠ {err}" if err else ("✓" if b.get(action) else ""), "Faint")
            self.form.addWidget(st, r, 3)

    def _set(self, action: str, ed: QKeySequenceEdit) -> None:
        text = hotkeys.normalize(ed.keySequence())
        if not text or text == hotkeys.bindings().get(action, ""):
            return
        try:
            err = hotkeys.HotkeyManager.instance().set_binding(action, text)
            if err:
                QMessageBox.warning(self, "Atalho", err)
        except ValueError as e:
            QMessageBox.warning(self, "Atalho", str(e))
        QTimer.singleShot(0, self.render)

    def _clear(self, action: str) -> None:
        hotkeys.HotkeyManager.instance().set_binding(action, "")
        self.render()


# ========================================================= EXPORTAR/IMPORTAR
class ImportDialog(QDialog):
    def __init__(self, doc: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importar visual")
        self.resize(560, 520)
        self.doc = doc
        pv = doc["_preview"]
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"“{doc.get('name', '')}” — criado em {doc.get('created', '?')} "
                            f"(PC Control Center {doc.get('app_version', '?')})", "Value", wrap=True))
        lay.addWidget(label("Escolha o que aplicar:", "Muted"))
        self.checks = {}
        for key in pv["parts"]:
            cb = QCheckBox(bundle.PARTS[key])
            cb.setChecked(True)
            self.checks[key] = cb
            lay.addWidget(cb)
        lay.addWidget(label("\n".join(f"• {s}" for s in pv["summary"]), "Faint", wrap=True))
        self.keep = QCheckBox("Manter os programas/sites que o arquivo abre (veja a lista)")
        if pv["programs"]:
            box = QPlainTextEdit("\n".join(pv["programs"]))
            box.setReadOnly(True)
            box.setFixedHeight(110)
            lay.addWidget(label("⚠ Este arquivo inclui atalhos que abrem estes programas/sites. Por segurança "
                                "eles serão REMOVIDOS, a menos que você marque a opção abaixo:", "Muted", wrap=True))
            lay.addWidget(box)
            lay.addWidget(self.keep)
        lay.addWidget(label("Mudanças no Windows (tema, cor, papel de parede) entram no Histórico de "
                            "personalização e podem ser desfeitas.", "Faint", wrap=True))
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Importar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def parts(self) -> set[str]:
        return {k for k, cb in self.checks.items() if cb.isChecked()}


class BundleView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)
        ex = GlassCard("Exportar meu visual", G.EXPORT)
        ex.add(label("Salva o seu visual num arquivo .pcctema para guardar, levar para outro PC ou compartilhar.",
                     "Faint", wrap=True))
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nome do visual (ex.: Setup gamer roxo)")
        ex.add(self.name)
        self.parts = {}
        for key, text in bundle.PARTS.items():
            cb = QCheckBox(text)
            cb.setChecked(key != "wallpaper")
            self.parts[key] = cb
            ex.add(cb)
        btn = QPushButton("Exportar...")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._export)
        ex.add(btn)
        self.ex_status = label("", "Muted", wrap=True)
        ex.add(self.ex_status)
        grid.add(ex)
        im = GlassCard("Importar visual", G.EXPORT)
        im.add(label("Abra um arquivo .pcctema. Antes de aplicar, você vê tudo o que ele contém e escolhe as "
                     "partes. O arquivo é só dados — nada é executado ao abrir.", "Faint", wrap=True))
        ib = QPushButton("Escolher arquivo...")
        ib.setObjectName("Primary")
        ib.clicked.connect(self._import)
        im.add(ib)
        self.im_status = label("", "Muted", wrap=True)
        im.add(self.im_status)
        grid.add(im)
        lay.addWidget(grid)

    def _export(self) -> None:
        parts = {k for k, cb in self.parts.items() if cb.isChecked()}
        if not parts:
            return
        name = self.name.text().strip() or "Meu visual"
        default = os.path.join(os.path.expanduser("~"), "Documents", f"{name}.pcctema")
        f, _ = QFileDialog.getSaveFileName(self, "Exportar visual", default, "Tema do PC Control Center (*.pcctema)")
        if not f:
            return
        try:
            n = bundle.export(f, parts, name)
            self.ex_status.setText(f"✓ Salvo em {f} ({n / 1e6:.1f} MB)".replace(".", ",", 1) if n > 1e6
                                   else f"✓ Salvo em {f}")
        except Exception as e:     # noqa: BLE001
            self.ex_status.setText(f"Falhou: {e}")

    def _import(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Importar visual", os.path.expanduser("~"),
                                           "Tema do PC Control Center (*.pcctema);;Todos os arquivos (*.*)")
        if not f:
            return
        try:
            doc = bundle.read(f)
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Importar", str(e))
            return
        dlg = ImportDialog(doc, self)
        if not dlg.exec() or not dlg.parts():
            return
        try:
            warns = bundle.apply(doc, dlg.parts(), dlg.keep.isChecked())
            self.im_status.setText("✓ Visual importado." + (" Avisos: " + "; ".join(warns) if warns else ""))
        except Exception as e:     # noqa: BLE001
            self.im_status.setText(f"Falhou: {e}")


# ================================================================ PÁGINA
class ScenesPage(Page):
    title = "Cenários e estilo"
    subtitle = "Cenários de um clique, tema automático, papel de parede vivo, tela e atalhos de teclado"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tabs = Segmented([("scenes", "Cenários"), ("auto", "Tema automático"), ("live", "Papel de parede vivo"),
                               ("display", "Tela"), ("keys", "Atalhos"), ("bundle", "Exportar / importar")])
        self.add(self.tabs)
        self.views = {"scenes": ScenesView(self), "auto": AutoThemeView(), "live": LiveWallView(),
                      "display": DisplayView(), "keys": HotkeysView(), "bundle": BundleView()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.tabs.changed.connect(self.switch)
        self.switch("scenes")

    def switch(self, key: str) -> None:
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if key == "scenes":
            self.views["scenes"].render()
        elif key == "auto":
            self.views["auto"].refresh()
        elif key == "keys":
            self.views["keys"].render()
        self.relayout()

    def on_shown(self) -> None:
        self.switch(self.tabs.current() or "scenes")
