"""Personalização do Windows: aparência, papel de parede, temas, barra de tarefas, área de
trabalho/Explorer, atalhos, aplicativos padrão e histórico (tudo desfazível)."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget)

from ...core.winapi import is_admin, open_folder, shell_open
from ...personalization import accent, changes, defaults, shortcuts, themes, tweaks, wallpaper
from ..components import GlassCard, ResponsiveGrid, Segmented, ToggleSwitch, label
from ..icons import G
from ..tasks import run_task
from .common import ask as _ask, make_table
from .base import Page


def _thumbs(paths: list[str], w: int = 240, h: int = 135) -> list[tuple[str, QImage]]:
    """Carrega miniaturas fora da thread da interface (QImage é seguro em outras threads)."""
    out = []
    for p in paths:
        img = QImage(p)
        if not img.isNull():
            out.append((p, img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                        .copy(0, 0, w, h)))
    return out


class TweakRow(QWidget):
    """Linha de ajuste: título, descrição e interruptor/lista. Aplica em segundo plano."""

    def __init__(self, tweak: tweaks.Tweak, page: "PersonalizationPage") -> None:
        super().__init__()
        self.t, self.page = tweak, page
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        col = QVBoxLayout()
        col.setSpacing(1)
        title = tweak.title + ("  🛡" if tweak.admin else "")
        col.addWidget(label(title))
        desc = tweak.description
        if not tweak.supported:
            desc = f"Requer Windows build {tweak.min_build} ou mais recente. " + desc
        if tweak.explorer_restart:
            desc += " (aplicado após reiniciar o Explorer)"
        if desc:
            col.addWidget(label(desc, "Faint", wrap=True))
        h.addLayout(col, 1)
        if tweak.toggle:
            self.ctrl = ToggleSwitch()
            self.ctrl.setChecked(tweak.current_index() == 1)
            self.ctrl.toggled.connect(lambda on: self._apply(tweak.options[1 if on else 0][0]))
        else:
            self.ctrl = QComboBox()
            for v, text in tweak.options:
                self.ctrl.addItem(text, v)
            self.ctrl.setCurrentIndex(max(0, tweak.current_index()))
            self.ctrl.activated.connect(lambda _i: self._apply(self.ctrl.currentData()))
        self.ctrl.setEnabled(tweak.supported)
        h.addWidget(self.ctrl, 0, Qt.AlignRight | Qt.AlignVCenter)

    def reload(self) -> None:
        self.ctrl.blockSignals(True)
        if self.t.toggle:
            self.ctrl.setChecked(self.t.current_index() == 1)
        else:
            self.ctrl.setCurrentIndex(max(0, self.t.current_index()))
        self.ctrl.blockSignals(False)

    def _apply(self, value) -> None:
        self.ctrl.setEnabled(False)

        def done(_cid):
            self.ctrl.setEnabled(True)
            self.page.changed(self.t.explorer_restart)

        def fail(msg):
            self.ctrl.setEnabled(True)
            self.reload()
            if "Acesso negado" in msg or "WinError 5" in msg:
                msg = ("O Windows bloqueou esta alteração por aplicativos externos (proteção do sistema). "
                       "Use o app Configurações para este item.") if not self.t.admin else \
                    "Este ajuste exige executar como administrador (Configurações → Reiniciar como administrador)."
            QMessageBox.warning(self, self.t.title, msg)

        run_task(self.t.apply, value, on_done=done, on_error=fail)


class PersonalizationPage(Page):
    title = "Personalização do Windows"
    subtitle = "Aparência, papel de parede, temas, barra de tarefas e mais — tudo pode ser desfeito"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[TweakRow] = []
        self.tabs = Segmented([("look", "Aparência"), ("wall", "Papel de parede"), ("themes", "Temas"),
                               ("taskbar", "Barra de tarefas"), ("desktop", "Área de trabalho"),
                               ("shortcuts", "Atalhos"), ("defaults", "Apps padrão"), ("history", "Histórico")])
        self.add(self.tabs)

        self.restart_card = GlassCard()
        rh = QHBoxLayout()
        rh.addWidget(label("⟳  Algumas alterações só aparecem depois de reiniciar o Explorer "
                           "(barra de tarefas e área de trabalho piscam por 2 segundos).", "Muted", wrap=True), 1)
        rb = QPushButton("Reiniciar Explorer agora")
        rb.setObjectName("Primary")
        rb.clicked.connect(self._restart_explorer)
        rh.addWidget(rb)
        self.restart_card.add(rh)
        self.restart_card.hide()
        self.add(self.restart_card)

        self.views = {"look": self._build_look(), "wall": self._build_wallpaper(), "themes": self._build_themes(),
                      "taskbar": self._build_taskbar(), "desktop": self._build_desktop(),
                      "shortcuts": self._build_shortcuts(), "defaults": self._build_defaults(),
                      "history": self._build_history()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.current = "look"
        self._loaded: set[str] = set()
        self.tabs.changed.connect(self.switch)
        self.switch("look")

    # ------------------------------------------------------------- utilidades
    @staticmethod
    def _section(title: str, glyph: str) -> GlassCard:
        return GlassCard(title, glyph)

    def _tweak_rows(self, card: GlassCard, section: str) -> None:
        for t in tweaks.TWEAKS:
            if t.section == section:
                r = TweakRow(t, self)
                self.rows.append(r)
                card.add(r)

    def changed(self, needs_restart: bool = False) -> None:
        if needs_restart:
            self.restart_card.show()
        self._load_history()

    def _restart_explorer(self) -> None:
        if _ask(self, "Reiniciar Explorer", "Reiniciar o Explorer agora?",
                "A barra de tarefas e a área de trabalho somem por alguns segundos. Janelas de pastas abertas "
                "serão fechadas (seus programas continuam abertos).", "Reiniciar"):
            run_task(changes.restart_explorer, on_done=lambda _r: self.restart_card.hide())

    def switch(self, key: str) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if key not in self._loaded:
            self._loaded.add(key)
            {"wall": self._load_wallpapers, "themes": self._load_themes, "defaults": self._load_defaults,
             "history": self._load_history, "shortcuts": self._load_created}.get(key, lambda: None)()
        for r in self.rows:
            r.reload()

    def on_shown(self) -> None:
        for r in self.rows:
            r.reload()
        self._refresh_accent()

    # ============================================================== APARÊNCIA
    def _build_look(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=480, max_cols=2)

        mode = self._section("Modo claro / escuro", G.PERSONALIZE)
        quick = QHBoxLayout()
        for text, val in (("Tudo escuro", 0), ("Tudo claro", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=val: self._all_mode(v))
            quick.addWidget(b)
        quick.addStretch(1)
        mode.add(quick)
        self._tweak_rows(mode, "appearance")
        grid.add(mode)

        acc = self._section("Cor de destaque", G.PERSONALIZE)
        top = QHBoxLayout()
        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(46, 46)
        top.addWidget(self.accent_swatch)
        self.accent_label = label("", "Value")
        top.addWidget(self.accent_label, 1)
        custom = QPushButton("Personalizada...")
        custom.clicked.connect(self._custom_accent)
        top.addWidget(custom)
        acc.add(top)
        sw = QGridLayout()
        sw.setSpacing(6)
        for i, c in enumerate(accent.PRESETS):
            b = QPushButton()
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(c)
            b.setStyleSheet(f"QPushButton {{ background: {c}; border-radius: 6px; border: 2px solid transparent; }}"
                            f"QPushButton:hover {{ border-color: white; }}")
            b.clicked.connect(lambda _=False, col=c: self._set_accent(col))
            sw.addWidget(b, i // 11, i % 11)
        acc.add(sw)
        auto_row = QHBoxLayout()
        auto_row.addWidget(label("Escolher automaticamente pelo papel de parede"), 1)
        self.auto_accent = ToggleSwitch()
        self.auto_accent.toggled.connect(
            lambda on: run_task(accent.set_auto_from_wallpaper, on, on_done=lambda _r: self._refresh_accent()))
        auto_row.addWidget(self.auto_accent)
        acc.add(auto_row)
        grid.add(acc)

        fx = self._section("Efeitos visuais", G.PERFORMANCE)
        anim = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Efeitos de animação"))
        col.addWidget(label("Animações ao abrir, minimizar e rolar. Desligar deixa PCs mais lentos mais ágeis.",
                            "Faint", wrap=True))
        anim.addLayout(col, 1)
        self.anim_toggle = ToggleSwitch()
        self.anim_toggle.setChecked(tweaks.get_animations())
        self.anim_toggle.toggled.connect(lambda on: run_task(tweaks.set_animations, on, on_done=lambda _r: self.changed()))
        anim.addWidget(self.anim_toggle)
        fx.add(anim)
        grid.add(fx)
        lay.addWidget(grid)
        self._refresh_accent()
        return w

    def _refresh_accent(self) -> None:
        cur = accent.current()
        self.accent_swatch.setStyleSheet(f"background: {cur['color']}; border-radius: 10px;")
        self.accent_label.setText(f"{cur['color']}" + ("  · automática" if cur["auto"] else ""))
        self.auto_accent.blockSignals(True)
        self.auto_accent.setChecked(cur["auto"])
        self.auto_accent.blockSignals(False)

    def _set_accent(self, color: str) -> None:
        run_task(accent.set_accent, color, on_done=lambda _r: (self._refresh_accent(), self.changed()),
                 on_error=lambda e: QMessageBox.warning(self, "Cor de destaque", e))

    def _custom_accent(self) -> None:
        c = QColorDialog.getColor(QColor(accent.current()["color"]), self, "Cor de destaque")
        if c.isValid():
            self._set_accent(c.name().upper())

    def _all_mode(self, light: int) -> None:
        def work():
            tweaks.TWEAK_BY_ID["apps_mode"].apply(light)
            tweaks.TWEAK_BY_ID["system_mode"].apply(light)
        run_task(work, on_done=lambda _r: (self.on_shown(), self.changed()))

    # ========================================================== PAPEL DE PAREDE
    def _build_wallpaper(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        cur = self._section("Papel de parede atual", "")
        row = QHBoxLayout()
        self.wp_preview = QLabel()
        self.wp_preview.setFixedSize(320, 180)
        self.wp_preview.setStyleSheet("border-radius: 10px; background: rgba(255,255,255,0.05);")
        row.addWidget(self.wp_preview)
        col = QVBoxLayout()
        self.wp_path = label("", "Muted", wrap=True)
        col.addWidget(self.wp_path)
        style_row = QHBoxLayout()
        style_row.addWidget(label("Ajuste:"))
        self.wp_style = QComboBox()
        for k, text in wallpaper.STYLE_LABELS.items():
            self.wp_style.addItem(text, k)
        self.wp_style.activated.connect(lambda _i: self._apply_wallpaper(wallpaper.current_path()))
        style_row.addWidget(self.wp_style)
        style_row.addStretch(1)
        col.addLayout(style_row)
        choose = QPushButton("Escolher imagem do computador...")
        choose.setObjectName("Primary")
        choose.clicked.connect(self._choose_wallpaper)
        col.addWidget(choose, 0, Qt.AlignLeft)
        folder = QPushButton("Abrir pasta das imagens anteriores")
        folder.clicked.connect(lambda: open_folder(str(wallpaper.backup_dir())))
        col.addWidget(folder, 0, Qt.AlignLeft)
        col.addStretch(1)
        row.addLayout(col, 1)
        cur.add(row)
        lay.addWidget(cur)

        self.wp_gallery_card = self._section("Imagens do Windows — clique para aplicar", G.WIDGETS)
        self.wp_gallery = ResponsiveGrid(min_col_width=200, max_cols=5, spacing=10)
        self.wp_gallery_card.add(self.wp_gallery)
        lay.addWidget(self.wp_gallery_card)
        self.wp_prev_card = self._section("Papéis de parede anteriores (cópias de segurança)", G.HISTORY)
        self.wp_prev = ResponsiveGrid(min_col_width=200, max_cols=5, spacing=10)
        self.wp_prev_card.add(self.wp_prev)
        lay.addWidget(self.wp_prev_card)
        return w

    def _thumb_button(self, path: str, img: QImage, on_click) -> QPushButton:
        b = QPushButton()
        b.setFixedHeight(118)
        b.setIcon(QPixmap.fromImage(img))
        b.setIconSize(QSize(200, 112))
        b.setToolTip(os.path.basename(path))
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("QPushButton { padding: 2px; border-radius: 10px; }")
        b.clicked.connect(lambda _=False, p=path: on_click(p))
        return b

    def _load_wallpapers(self) -> None:
        path = wallpaper.current_path()
        self.wp_path.setText(path or "(cor sólida ou nenhum)")
        self.wp_style.setCurrentIndex(max(0, self.wp_style.findData(wallpaper.current_style())))
        if path and os.path.isfile(path):
            run_task(_thumbs, [path], 320, 180,
                     on_done=lambda r: r and self.wp_preview.setPixmap(QPixmap.fromImage(r[0][1])))
        self._fill_grid(self.wp_gallery, wallpaper.builtin_wallpapers())
        prev = wallpaper.previous_wallpapers()
        self.wp_prev_card.setVisible(bool(prev))
        self._fill_grid(self.wp_prev, prev)

    def _fill_grid(self, grid: ResponsiveGrid, paths: list[str]) -> None:
        def done(items):
            for _w, _s in list(grid._items):
                _w.deleteLater()
            grid._items.clear()
            for p, img in items:
                grid.add(self._thumb_button(p, img, self._apply_wallpaper))
            self.relayout()
        run_task(_thumbs, paths, 200, 112, on_done=done)

    def _choose_wallpaper(self) -> None:
        start = os.path.join(os.path.expanduser("~"), "Pictures")
        path, _ = QFileDialog.getOpenFileName(self, "Escolher papel de parede", start,
                                              "Imagens (*.jpg *.jpeg *.png *.bmp *.gif *.webp *.jfif *.tif)")
        if path:
            self._apply_wallpaper(path)

    def _apply_wallpaper(self, path: str) -> None:
        style = self.wp_style.currentData()

        def done(_cid):
            self._load_wallpapers()
            self.changed()

        run_task(wallpaper.set_wallpaper, path, style, on_done=done,
                 on_error=lambda e: QMessageBox.warning(self, "Papel de parede", e))

    # =================================================================== TEMAS
    def _build_themes(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Temas instalados", G.PERSONALIZE)
        card.add(label("Um tema troca papel de parede, cores, sons e cursores de uma vez. O Windows aplica o tema e "
                       "pode abrir a página de Personalização. Para voltar, use o Histórico.", "Muted", wrap=True))
        self.theme_grid = ResponsiveGrid(min_col_width=250, max_cols=4, spacing=12)
        card.add(self.theme_grid)
        more = QPushButton("Mais temas na Microsoft Store")
        more.clicked.connect(lambda: shell_open("ms-windows-store://collection?CollectionId=Themes"))
        card.add(more)
        lay.addWidget(card)
        return w

    def _load_themes(self) -> None:
        items = themes.list_themes()
        for _w, _s in list(self.theme_grid._items):
            _w.deleteLater()
        self.theme_grid._items.clear()
        pics: dict[str, list[QLabel]] = {}   # vários temas podem usar a mesma imagem
        # Os cartões aparecem na hora; as miniaturas (imagens 4K) chegam depois.
        for t in items:
            tile = GlassCard()
            pic = QLabel("carregando...")
            pic.setObjectName("Faint")
            pic.setFixedHeight(130)
            pic.setAlignment(Qt.AlignCenter)
            if t.wallpaper:
                pics.setdefault(t.wallpaper, []).append(pic)
            else:
                pic.setText("(sem papel de parede)")
            tile.add(pic)
            head = QHBoxLayout()
            head.addWidget(label(t.name, "Value"), 1)
            if t.mode:
                head.addWidget(label(t.mode, "Badge"))
            tile.add(head)
            btn = QPushButton("Em uso" if t.current else "Aplicar tema")
            btn.setObjectName("" if t.current else "Primary")
            btn.setEnabled(not t.current)
            btn.clicked.connect(lambda _=False, th=t: self._apply_theme(th))
            tile.add(btn)
            self.theme_grid.add(tile)
        self.relayout()

        def done(thumbs):
            for path, img in thumbs:
                pm = QPixmap.fromImage(img)
                for pic in pics.get(path, []):
                    pic.setPixmap(pm)

        run_task(_thumbs, list(pics), 230, 130, on_done=done)

    def _apply_theme(self, t: themes.ThemeInfo) -> None:
        if not _ask(self, "Aplicar tema", f"Aplicar o tema “{t.name}”?",
                    "Papel de parede, cores e sons serão trocados pelo Windows. Você pode voltar ao tema atual "
                    "pela aba Histórico.", "Aplicar"):
            return
        try:
            themes.apply_theme(t.path)
        except Exception as e:
            QMessageBox.warning(self, "Tema", str(e))
            return
        self.changed()
        self._loaded.discard("themes")

    # ======================================================== BARRA DE TAREFAS
    def _build_taskbar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Barra de tarefas", "")
        self._tweak_rows(card, "taskbar")
        ah = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Ocultar a barra de tarefas automaticamente"))
        col.addWidget(label("A barra aparece ao levar o mouse até a borda da tela.", "Faint"))
        ah.addLayout(col, 1)
        self.autohide = ToggleSwitch()
        self.autohide.setChecked(tweaks.taskbar_autohide())
        self.autohide.toggled.connect(lambda on: (tweaks.set_taskbar_autohide(on), self.changed()))
        ah.addWidget(self.autohide)
        card.add(ah)
        more = QPushButton("Mais opções da barra de tarefas no Windows")
        more.clicked.connect(lambda: shell_open("ms-settings:taskbar"))
        card.add(more)
        lay.addWidget(card)
        return w

    # ============================================== ÁREA DE TRABALHO E EXPLORER
    def _build_desktop(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)
        icons = self._section("Ícones da área de trabalho", "")
        self._tweak_rows(icons, "desktop")
        grid.add(icons)
        exp = self._section("Explorador de Arquivos", G.FOLDER)
        self._tweak_rows(exp, "explorer")
        cm = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Menu de contexto clássico (botão direito completo)"))
        col.addWidget(label("Mostra o menu completo do Windows 10 sem precisar de “Mostrar mais opções”. "
                            "Aplicado após reiniciar o Explorer.", "Faint", wrap=True))
        cm.addLayout(col, 1)
        self.classic = ToggleSwitch()
        self.classic.setChecked(tweaks.classic_menu_enabled())
        self.classic.setEnabled(tweaks.BUILD >= 22000)
        self.classic.toggled.connect(lambda on: run_task(tweaks.set_classic_menu, on,
                                                         on_done=lambda _r: self.changed(True)))
        cm.addWidget(self.classic)
        exp.add(cm)
        grid.add(exp)
        sysc = self._section("Inicialização do sistema", G.POWER)
        self._tweak_rows(sysc, "system")
        go = QPushButton("Gerenciar programas que iniciam com o Windows")
        go.clicked.connect(self._go_startup)
        sysc.add(go)
        if not is_admin():
            sysc.add(label("🛡 = exige executar o PC Control Center como administrador.", "Faint"))
        grid.add(sysc)
        lay.addWidget(grid)
        return w

    def _go_startup(self) -> None:
        win = self.window()
        if hasattr(win, "show_page"):
            win.show_page(3)
            page = win.stack.widget(3)
            if hasattr(page, "switch"):
                page.switch("startup")

    # =================================================================== ATALHOS
    def _build_shortcuts(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=480, max_cols=2)
        form = self._section("Criar atalho", "")
        g = QGridLayout()
        g.setVerticalSpacing(8)
        self.sc_name = QLineEdit()
        self.sc_name.setPlaceholderText("Nome do atalho")
        self.sc_target = QLineEdit()
        self.sc_target.setPlaceholderText("Programa, pasta ou site (https://...)")
        self.sc_args = QLineEdit()
        self.sc_args.setPlaceholderText("Argumentos (opcional)")
        self.sc_where = QComboBox()
        self.sc_where.addItem("Área de trabalho", "desktop")
        self.sc_where.addItem("Menu Iniciar", "start")
        pick_file = QPushButton("Programa...")
        pick_file.clicked.connect(self._pick_target_file)
        pick_dir = QPushButton("Pasta...")
        pick_dir.clicked.connect(self._pick_target_dir)
        g.addWidget(label("Nome"), 0, 0)
        g.addWidget(self.sc_name, 0, 1, 1, 3)
        g.addWidget(label("Destino"), 1, 0)
        g.addWidget(self.sc_target, 1, 1)
        g.addWidget(pick_file, 1, 2)
        g.addWidget(pick_dir, 1, 3)
        g.addWidget(label("Argumentos"), 2, 0)
        g.addWidget(self.sc_args, 2, 1, 1, 3)
        g.addWidget(label("Criar em"), 3, 0)
        g.addWidget(self.sc_where, 3, 1)
        form.add(g)
        create = QPushButton("Criar atalho")
        create.setObjectName("Primary")
        create.clicked.connect(self._create_custom)
        form.add(create)
        grid.add(form)

        tpl = self._section("Modelos prontos", G.LIST)
        for name, target, args, icon, desc in shortcuts.TEMPLATES:
            r = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(name))
            col.addWidget(label(desc, "Faint"))
            r.addLayout(col, 1)
            b = QPushButton("Criar na área de trabalho")
            b.clicked.connect(lambda _=False, a=(name, target, args, icon): self._create(*a))
            r.addWidget(b)
            tpl.add(r)
        r = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("PC Control Center"))
        col.addWidget(label("Atalho para este aplicativo", "Faint"))
        r.addLayout(col, 1)
        b = QPushButton("Criar na área de trabalho")
        b.clicked.connect(lambda: self._create("PC Control Center", *shortcuts.app_target(), ""))
        r.addWidget(b)
        tpl.add(r)
        grid.add(tpl)
        lay.addWidget(grid)

        created = self._section("Atalhos criados pelo PC Control Center", G.HISTORY)
        self.created_table = make_table(["Data", "Atalho", "Destino"], stretch=2)
        self.created_table.setMinimumHeight(170)
        created.add(self.created_table)
        rm = QPushButton("Remover atalho selecionado")
        rm.setObjectName("Danger")
        rm.clicked.connect(self._remove_created)
        created.add(rm)
        lay.addWidget(created)
        return w

    def _pick_target_file(self) -> None:
        start = os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
        path, _ = QFileDialog.getOpenFileName(self, "Escolher programa", start, "Programas (*.exe *.lnk *.bat *.cmd);;"
                                                                                "Todos os arquivos (*.*)")
        if path:
            self.sc_target.setText(os.path.normpath(path))
            if not self.sc_name.text():
                self.sc_name.setText(os.path.splitext(os.path.basename(path))[0])

    def _pick_target_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta")
        if path:
            self.sc_target.setText(os.path.normpath(path))
            if not self.sc_name.text():
                self.sc_name.setText(os.path.basename(path))

    def _create_custom(self) -> None:
        target = self.sc_target.text().strip()
        if target and "://" not in target and "." in target and " " not in target and not os.path.exists(target):
            target = "https://" + target   # "google.com" → site
        self._create(self.sc_name.text().strip() or "Atalho", target, self.sc_args.text().strip(), "",
                     self.sc_where.currentData())

    def _create(self, name, target, args, icon, where="desktop") -> None:
        try:
            shortcuts.create_shortcut(name, target, args, where, icon)
        except Exception as e:
            QMessageBox.warning(self, "Criar atalho", str(e))
            return
        self._load_created()
        self.changed()

    def _load_created(self) -> None:
        rows = [h for h in changes.history(300) if h["kind"] == "shortcut" and not h["restored"]
                and os.path.exists(h["data"].get("path", ""))]
        self._created = rows
        t = self.created_table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, h in enumerate(rows):
            for c, text in enumerate([datetime.fromtimestamp(h["ts"]).strftime("%d/%m/%Y %H:%M"),
                                      os.path.basename(h["data"]["path"]), h["data"].get("target", "")]):
                t.setItem(r, c, QTableWidgetItem(text))

    def _remove_created(self) -> None:
        r = self.created_table.currentRow()
        if r < 0 or r >= len(getattr(self, "_created", [])):
            return
        h = self._created[r]
        if _ask(self, "Remover atalho", f"Remover “{os.path.basename(h['data']['path'])}”?",
                f"Será apagado exatamente este arquivo:\n{h['data']['path']}\n\n"
                "O programa, a pasta ou o site de destino não são afetados.", "Remover"):
            try:
                changes.undo(h["id"])
            except PermissionError as e:
                QMessageBox.warning(self, "Remover atalho", str(e))
            self._load_created()
            self._load_history()

    # ============================================================= APPS PADRÃO
    def _build_defaults(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Aplicativos padrão", G.APPS)
        card.add(label("O Windows protege os aplicativos padrão contra alterações por outros programas — por "
                       "segurança, a troca é feita na tela oficial do Windows (botão abaixo).", "Muted", wrap=True))
        self.def_table = make_table(["Tipo", "Extensão / protocolo", "Aplicativo atual"], stretch=2)
        self.def_table.setMinimumHeight(380)
        card.add(self.def_table)
        btns = QHBoxLayout()
        ch = QPushButton("Alterar aplicativos padrão no Windows")
        ch.setObjectName("Primary")
        ch.clicked.connect(lambda: shell_open("ms-settings:defaultapps"))
        btns.addWidget(ch)
        rf = QPushButton("Atualizar")
        rf.clicked.connect(self._load_defaults)
        btns.addWidget(rf)
        btns.addStretch(1)
        card.add(btns)
        lay.addWidget(card)
        return w

    def _load_defaults(self) -> None:
        def done(items):
            t = self.def_table
            t.setSortingEnabled(False)
            t.setRowCount(len(items))
            for r, d in enumerate(items):
                for c, text in enumerate([d.category, d.kind, d.app_name]):
                    t.setItem(r, c, QTableWidgetItem(text))
        run_task(defaults.list_defaults, on_done=done)

    # ================================================================ HISTÓRICO
    def _build_history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Histórico de alterações", G.HISTORY)
        card.add(label("Cada alteração feita por aqui tem cópia de segurança. Selecione e clique em Desfazer para "
                       "voltar ao estado anterior.", "Muted", wrap=True))
        self.hist_table = make_table(["Data", "Alteração", "Situação"], stretch=1)
        self.hist_table.setMinimumHeight(380)
        card.add(self.hist_table)
        btns = QHBoxLayout()
        undo = QPushButton("Desfazer selecionada")
        undo.setObjectName("Primary")
        undo.clicked.connect(self._undo_selected)
        btns.addWidget(undo)
        btns.addStretch(1)
        card.add(btns)
        lay.addWidget(card)
        return w

    def _load_history(self) -> None:
        self._hist = changes.history(200)
        t = self.hist_table
        t.setSortingEnabled(False)
        t.setRowCount(len(self._hist))
        for r, h in enumerate(self._hist):
            state = "desfeita" if h["restored"] else "ativa"
            for c, text in enumerate([datetime.fromtimestamp(h["ts"]).strftime("%d/%m/%Y %H:%M:%S"), h["title"],
                                      state]):
                item = QTableWidgetItem(text)
                if h["restored"]:
                    item.setForeground(QColor("#94a3b8"))
                t.setItem(r, c, item)

    def _undo_selected(self) -> None:
        r = self.hist_table.currentRow()
        if r < 0 or r >= len(getattr(self, "_hist", [])):
            QMessageBox.information(self, "Desfazer", "Selecione uma alteração na lista.")
            return
        h = self._hist[r]
        if h["restored"]:
            QMessageBox.information(self, "Desfazer", "Esta alteração já foi desfeita.")
            return
        detail = "O estado anterior será restaurado."
        if h["kind"] == "shortcut":
            detail = (f"Será apagado exatamente este arquivo de atalho:\n{h['data'].get('path', '')}\n\n"
                      "O programa, a pasta ou o site de destino não são afetados.")
        if not _ask(self, "Desfazer", f"Desfazer “{h['title']}”?", detail, "Desfazer"):
            return

        def done(msg):
            self._load_history()
            self.on_shown()
            self._loaded.discard("wall")
            self._loaded.discard("themes")
            if "Explorer" in msg:
                self.restart_card.show()
            QMessageBox.information(self, "Desfazer", msg)

        run_task(changes.undo, h["id"], on_done=done, on_error=lambda e: QMessageBox.warning(self, "Desfazer", e))
