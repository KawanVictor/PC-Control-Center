"""Ferramentas do sistema: atalhos para utilitários nativos do Windows.

Ferramentas que alteram o sistema (SFC/DISM) pedem confirmação e abrem um console
elevado visível — nada é executado silenciosamente.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from ...core.winapi import shell_open
from ..components import GlassCard, ResponsiveGrid, icon_label, label
from ..icons import G
from .base import Page

# (título, descrição, glifo, alvo, argumentos, precisa de admin, confirmação)
TOOLS = [
    ("Gerenciador de Tarefas", "Processos, desempenho e inicialização", G.TASKS, "taskmgr.exe", "", False, None),
    ("Gerenciador de Dispositivos", "Drivers e hardware instalado", G.DEVICES, "devmgmt.msc", "", False, None),
    ("Serviços do Windows", "Visualizar e gerenciar serviços", G.SERVICES, "services.msc", "", False, None),
    ("Gerenciamento de Disco", "Partições e volumes", G.DISK, "diskmgmt.msc", "", False, None),
    ("Configurações do Windows", "Painel de configurações do sistema", G.SETTINGS, "ms-settings:", "", False, None),
    ("Monitor de Recursos", "CPU, memória, disco e rede em detalhe", G.PERFORMANCE, "resmon.exe", "", False, None),
    ("Prompt de Comando", "Terminal cmd.exe", G.TERMINAL, "cmd.exe", "", False, None),
    ("PowerShell", "Terminal PowerShell", G.TERMINAL, "powershell.exe", "", False, None),
    ("Informações do Sistema", "Relatório completo de hardware e software", G.INFO, "msinfo32.exe", "", False, None),
    ("Status de rede", "Diagnóstico e solução de problemas de rede", G.NETWORK, "ms-settings:network-status", "",
     False, None),
    ("Visualizador de Eventos", "Logs de erros e eventos do sistema", G.LIST, "eventvwr.msc", "", False, None),
    ("Limpeza de Disco", "Ferramenta oficial de limpeza do Windows", G.FOLDER, "cleanmgr.exe", "", False, None),
    ("Verificar integridade (SFC)", "Verifica e repara arquivos do sistema", G.SHIELD, "cmd.exe",
     "/k sfc /scannow", True,
     "Será aberto um Prompt de Comando como administrador executando:\n\n    sfc /scannow\n\n"
     "A verificação pode levar de 5 a 20 minutos e só repara arquivos protegidos do Windows. Continuar?"),
    ("Reparar imagem (DISM)", "Restaura a imagem do Windows via Windows Update", G.SHIELD, "cmd.exe",
     "/k DISM /Online /Cleanup-Image /RestoreHealth", True,
     "Será aberto um Prompt de Comando como administrador executando:\n\n"
     "    DISM /Online /Cleanup-Image /RestoreHealth\n\n"
     "Requer internet e pode levar de 10 a 30 minutos. Continuar?"),
]


class ToolsPage(Page):
    title = "Ferramentas do sistema"
    subtitle = "Acesso rápido aos utilitários oficiais do Windows"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        grid = ResponsiveGrid(min_col_width=260, max_cols=4, spacing=12)
        for title, desc, glyph, target, args, admin, confirm in TOOLS:
            btn = QPushButton()
            btn.setObjectName("Tile")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(86)
            lay = QHBoxLayout(btn)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(14)
            ic = icon_label(glyph, 18)
            ic.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(ic)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = label(title + ("  🛡" if admin else ""), "Value")
            t.setStyleSheet("font-size: 10.5pt;")
            d = label(desc, "Faint", wrap=True)
            for w in (t, d):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
                col.addWidget(w)
            lay.addLayout(col, 1)
            btn.clicked.connect(lambda _=False, a=(title, target, args, admin, confirm): self._launch(*a))
            grid.add(btn)
        self.add(grid)
        note = GlassCard()
        note.add(label("🛡 = requer permissão de administrador (o Windows mostrará o aviso do UAC). "
                       "Todas as ações ficam registradas no log de operações.", "Muted", wrap=True))
        self.add(note)
        self.layout_.addStretch(1)

    def _launch(self, title: str, target: str, args: str, admin: bool, confirm: str | None) -> None:
        if confirm:
            res = QMessageBox.question(self, title, confirm, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if res != QMessageBox.Yes:
                return
        if not shell_open(target, args, admin=admin):
            QMessageBox.warning(self, title, "Não foi possível abrir a ferramenta (ou a permissão foi negada).")
