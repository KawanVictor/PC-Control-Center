"""Aba Cenários: lista de cenários e o editor de cenário."""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ....core.config import Settings
from ....personalization import hotkeys, power, scenes
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G
from ..common import ask

if TYPE_CHECKING:
    from . import ScenesPage


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

        from ....widgets.manager import WidgetManager
        prof = self._combo([(n, n) for n in WidgetManager.instance().profile_names()], self.actions.get("widgets_profile"))
        self._add("widgets_profile", prof, prof.currentData)
        wv = self._combo([(True, "Mostrar"), (False, "Ocultar")], self.actions.get("widgets_visible"))
        self._add("widgets_visible", wv, wv.currentData)

        try:
            from ....media import audio
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
        from ....media.obs import ObsClient
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
    def __init__(self, page: ScenesPage) -> None:
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
        if ask(self, "Excluir cenário", f"Excluir o cenário “{sc['name']}”?",
                "Só a configuração do cenário é apagada; nada no Windows muda.", "Excluir"):
            if scenes.active().get("id") == sc["id"]:
                scenes.deactivate()
            scenes.remove(sc["id"])
            self.render()

    def _reset(self) -> None:
        if ask(self, "Cenários padrão", "Restaurar os 4 cenários padrão?",
                "Cenários que você criou ou editou serão substituídos.", "Restaurar"):
            if scenes.active():
                scenes.deactivate()
            Settings.instance().set("scenes.list", [])
            self.render()
