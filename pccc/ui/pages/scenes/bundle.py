"""Aba Exportar/importar: pacote .pcctema com o estilo do PC."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ....personalization import bundle
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G


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
