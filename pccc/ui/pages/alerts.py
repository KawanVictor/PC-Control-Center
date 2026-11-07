"""Alertas e automações: central de alertas, regras, diagnóstico/sugestões e relatórios."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout, QMessageBox, QProgressBar, QPushButton,
                               QSpinBox, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from ...automation import advisor, reports, store
from ...automation.engine import AlertEngine
from ...automation.notifier import QUNS, Notifier
from ...automation.rules import load_rules, reset_rules, save_rule
from ...automation.store import Alert
from ...core.config import Settings
from ...core.winapi import open_folder
from ...monitoring.collector import MonitorService
from ...network.monitor import NetworkService
from ..components import GlassCard, ResponsiveGrid, Segmented, ToggleSwitch, icon_label, label, stat_block
from ..fmt import fmt_bytes
from ..icons import G
from ..tasks import run_task
from .apps import make_table
from .base import Page

SEV_COLOR = {"critical": "#fb7185", "warning": "#fbbf24", "info": "#38bdf8", "tip": "#38bdf8", "ok": "#34d399"}
SEV_TEXT = {"critical": "Crítico", "warning": "Atenção", "info": "Info", "tip": "Dica", "ok": "OK"}


def _row(title: str, desc: str, control) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 4, 0, 4)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(label(title))
    if desc:
        col.addWidget(label(desc, "Faint", wrap=True))
    h.addLayout(col, 1)
    h.addWidget(control)
    return w


class AlertsPage(Page):
    title = "Alertas e automações"
    subtitle = "Avisos inteligentes, diagnóstico de desempenho, sugestões e relatórios"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.s = Settings.instance()
        self.engine = AlertEngine.instance()
        self.tabs = Segmented([("center", "Central de alertas"), ("rules", "Regras e notificações"),
                               ("diag", "Diagnóstico e sugestões"), ("reports", "Relatórios")])
        self.header_right.addWidget(self.tabs)
        self.views = {"center": self._build_center(), "rules": self._build_rules(), "diag": self._build_diag(),
                      "reports": self._build_reports()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.current = "center"
        self._diag_done = False
        self.tabs.changed.connect(self.switch)
        self.engine.fired.connect(lambda _a: self.isVisible() and self.current == "center" and self._load_alerts())
        self.switch("center")

    def switch(self, key: str) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if key == "center":
            self._load_alerts()
        elif key == "diag" and not self._diag_done:
            self._analyze()
        elif key == "reports" and not getattr(self, "_rep", None):
            self._generate()

    def on_shown(self) -> None:
        self.switch(self.current)
        if self.current == "center":
            store.mark_all_read()
            self.engine.unread_changed.emit(0)

    # ================================================================ CENTRAL
    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        top = ResponsiveGrid(min_col_width=220, max_cols=4, spacing=12)
        self.sm = {}
        for key, title in (("today", "Alertas hoje"), ("week", "Últimos 7 dias"), ("state", "Notificações"),
                           ("focus", "Windows agora")):
            c = GlassCard()
            wdg, v = stat_block(title)
            v.setObjectName("BigValue")
            v.setStyleSheet("font-size: 16pt;")
            c.add(wdg)
            top.add(c)
            self.sm[key] = v
        lay.addWidget(top)

        card = GlassCard("Histórico de alertas", G.ALERTS)
        btns = QHBoxLayout()
        self.snooze_btn = QPushButton("Silenciar por 1 hora")
        self.snooze_btn.clicked.connect(self._toggle_snooze)
        test = QPushButton("Testar notificação")
        test.clicked.connect(self._test_notification)
        read = QPushButton("Marcar todos como lidos")
        read.clicked.connect(lambda: (store.mark_all_read(), self.engine.unread_changed.emit(0), self._load_alerts()))
        clear = QPushButton("Limpar histórico")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear)
        for b in (self.snooze_btn, test, read):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(clear)
        card.add(btns)
        self.table = make_table(["Quando", "Nível", "Alerta", "Detalhes"], stretch=3)
        self.table.setWordWrap(True)
        self.table.setMinimumHeight(420)
        self.table.itemDoubleClicked.connect(self._open_alert)
        card.add(self.table)
        card.add(label("Clique duas vezes num alerta para ir à tela relacionada. Alertas durante jogos em tela cheia, "
                       "apresentações ou o “Não incomodar” do Windows ficam só aqui — exceto os críticos.",
                       "Faint", wrap=True))
        lay.addWidget(card)
        return w

    def _load_alerts(self) -> None:
        import time
        alerts = store.list_alerts(300)
        self._alerts = alerts
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(alerts))
        for r, a in enumerate(alerts):
            sev = QTableWidgetItem(("● " if not a.read else "○ ") + SEV_TEXT.get(a.severity, a.severity))
            sev.setForeground(QColor(SEV_COLOR.get(a.severity, "#94a3b8")))
            cells = [QTableWidgetItem(datetime.fromtimestamp(a.ts).strftime("%d/%m %H:%M:%S")), sev,
                     QTableWidgetItem(a.title), QTableWidgetItem(a.message)]
            cells[3].setToolTip(a.message)
            for c, item in enumerate(cells):
                t.setItem(r, c, item)
        t.resizeRowsToContents()
        now = time.time()
        self.sm["today"].setText(str(sum(1 for a in alerts if a.ts >= now - 86400)))
        self.sm["week"].setText(str(sum(1 for a in alerts if a.ts >= now - 7 * 86400)))
        n = Notifier.instance()
        if not self.s.get("notifications.enabled", True):
            state = "Desligadas"
        elif now < n.snoozed_until:
            state = f"Silenciadas até {datetime.fromtimestamp(n.snoozed_until):%H:%M}"
        else:
            state = "Ativas"
        self.sm["state"].setText(state)
        self.snooze_btn.setText("Reativar agora" if now < n.snoozed_until else "Silenciar por 1 hora")
        st = n.focus_state()
        self.sm["focus"].setText("Livre" if st == 5 else QUNS.get(st, "—").capitalize())

    def _toggle_snooze(self) -> None:
        import time
        n = Notifier.instance()
        if time.time() < n.snoozed_until:
            n.snoozed_until = 0
        else:
            n.snooze(60)
        self._load_alerts()

    def _test_notification(self) -> None:
        a = Alert("test", "info", "Teste de notificação", "As notificações do PC Control Center estão funcionando.")
        shown = Notifier.instance().notify(a)
        if not shown:
            reason = Notifier.instance().blocked_reason(a) or "bandeja indisponível"
            QMessageBox.information(self, "Notificações", f"O balão não foi exibido agora: {reason}.")

    def _clear(self) -> None:
        if QMessageBox.question(self, "Limpar histórico", "Apagar todo o histórico de alertas?") == QMessageBox.Yes:
            store.clear_alerts()
            self.engine.unread_changed.emit(0)
            self._load_alerts()

    def _open_alert(self, item) -> None:
        r = item.row()
        if 0 <= r < len(getattr(self, "_alerts", [])):
            action = self._alerts[r].action
            win = self.window()
            if action and hasattr(win, "navigate"):
                win.navigate(action)

    # ================================================================== REGRAS
    def _build_rules(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        notif = GlassCard("Notificações", G.ALERTS)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)

        def toggle(key, default=True):
            t = ToggleSwitch()
            t.setChecked(bool(self.s.get(key, default)))
            t.toggled.connect(lambda v: self.s.set(key, v))
            return t

        grid.addWidget(_row("Mostrar notificações do Windows", "Os alertas sempre ficam registrados na Central.",
                            toggle("notifications.enabled")), 0, 0)
        grid.addWidget(_row("Não atrapalhar jogos, vídeos e apresentações",
                            "Respeita tela cheia e o “Não incomodar” do Windows (alertas críticos aparecem mesmo assim).",
                            toggle("notifications.respect_focus")), 0, 1)
        qh = QWidget()
        qhl = QHBoxLayout(qh)
        qhl.setContentsMargins(0, 0, 0, 0)
        qhl.addWidget(toggle("notifications.quiet_hours", False))
        for key, default in (("notifications.quiet_start", "22:00"), ("notifications.quiet_end", "07:00")):
            te = QTimeEdit(QTime.fromString(self.s.get(key, default), "HH:mm"))
            te.setDisplayFormat("HH:mm")
            te.timeChanged.connect(lambda t, k=key: self.s.set(k, t.toString("HH:mm")))
            qhl.addWidget(te)
        grid.addWidget(_row("Horário de silêncio", "Sem balões neste intervalo (ex.: à noite).", qh), 1, 0)
        grid.addWidget(_row("Relatório semanal automático",
                            "Gera um relatório dos últimos 7 dias uma vez por semana e avisa quando estiver pronto.",
                            toggle("alerts.weekly_report")), 1, 1)
        notif.add(grid)
        lay.addWidget(notif)

        rules_card = GlassCard("Regras de alerta", G.SETTINGS)
        reset = QPushButton("Restaurar padrões")
        reset.clicked.connect(self._reset_rules)
        rules_card.add_header_widget(reset)
        rules_card.add(label("Um alerta só dispara se a condição durar o tempo indicado, e não se repete antes do "
                             "intervalo — assim picos de 1 segundo não incomodam.", "Muted", wrap=True))
        self.rules_box = QVBoxLayout()
        self.rules_box.setSpacing(4)
        rules_card.add(self.rules_box)
        lay.addWidget(rules_card)
        self._fill_rules()
        return w

    def _fill_rules(self) -> None:
        while self.rules_box.count():
            it = self.rules_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for rule in load_rules().values():
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 6, 0, 6)
            en = ToggleSwitch()
            en.setChecked(rule.enabled)
            h.addWidget(en)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(rule.title))
            col.addWidget(label(rule.description, "Faint"))
            h.addLayout(col, 1)
            thr = QDoubleSpinBox()
            thr.setRange(rule.min_value, rule.max_value)
            thr.setSingleStep(rule.step)
            thr.setDecimals(1 if rule.step < 1 else 0)
            thr.setValue(rule.threshold)
            thr.setSuffix(f" {rule.unit}")
            thr.setMinimumWidth(110)
            h.addWidget(label("limite" if rule.kind != "internet" else "após", "Faint"))
            h.addWidget(thr)
            dur = QSpinBox()
            dur.setRange(0, 3600)
            dur.setSingleStep(15)
            dur.setSuffix(" s")
            dur.setValue(rule.duration)
            if rule.kind not in ("internet", "disk_free", "battery"):
                h.addWidget(label("por", "Faint"))
                h.addWidget(dur)
            cd = QSpinBox()
            cd.setRange(0, 1440)
            cd.setSingleStep(5)
            cd.setSuffix(" min")
            cd.setValue(rule.cooldown)
            if rule.kind != "internet":
                h.addWidget(label("repetir após", "Faint"))
                h.addWidget(cd)

            def save(_=None, r=rule, en=en, thr=thr, dur=dur, cd=cd):
                r.enabled, r.threshold, r.duration, r.cooldown = en.isChecked(), thr.value(), dur.value(), cd.value()
                if r.kind == "internet":
                    r.duration = int(r.threshold)
                save_rule(r)

            en.toggled.connect(save)
            thr.editingFinished.connect(save)
            dur.editingFinished.connect(save)
            cd.editingFinished.connect(save)
            self.rules_box.addWidget(w)
        self.relayout()

    def _reset_rules(self) -> None:
        reset_rules()
        self._fill_rules()

    # ============================================================== DIAGNÓSTICO
    def _build_diag(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)
        bn = GlassCard("Gargalo principal (última hora)", G.PERFORMANCE)
        again = QPushButton("Analisar agora")
        again.clicked.connect(self._analyze)
        bn.add_header_widget(again)
        self.bn_title = label("Analisando...", "BigValue")
        self.bn_detail = label("", "Muted", wrap=True)
        bn.add(self.bn_title)
        bn.add(self.bn_detail)
        self.bn_bars: dict[str, tuple] = {}
        for res in ("CPU", "Memória RAM", "GPU", "Disco"):
            r = QHBoxLayout()
            n = label(res)
            n.setFixedWidth(110)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            v = label("—", "Muted")
            v.setFixedWidth(50)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            r.addWidget(n)
            r.addWidget(bar, 1)
            r.addWidget(v)
            bn.add(r)
            self.bn_bars[res] = (bar, v)
        grid.add(bn)

        tools = GlassCard("Ferramentas de manutenção seguras", G.TOOLS)
        tools.add(label("Ferramentas oficiais do Windows. Este app não faz “limpeza de RAM” nem encerra processos "
                        "sozinho — isso costuma deixar o PC mais lento e pode perder dados.", "Faint", wrap=True))
        tg = QGridLayout()
        tg.setSpacing(8)
        for i, (name, desc, target, args) in enumerate(advisor.MAINTENANCE):
            b = QPushButton(name)
            b.setToolTip(desc)
            b.clicked.connect(lambda _=False, t=target, a=args, n=name: self._run_tool(n, t, a))
            tg.addWidget(b, i // 2, i % 2)
        tools.add(tg)
        grid.add(tools)
        lay.addWidget(grid)

        self.sugg_card = GlassCard("Sugestões de otimização", G.INFO)
        self.sugg_box = QVBoxLayout()
        self.sugg_box.setSpacing(10)
        self.sugg_card.add(self.sugg_box)
        lay.addWidget(self.sugg_card)
        return w

    def _run_tool(self, name: str, target: str, args: str) -> None:
        from ...core.winapi import shell_open
        if target == "mdsched.exe" and QMessageBox.question(
                self, name, "O Diagnóstico de Memória pede para reiniciar o computador para testar a RAM. Abrir?") \
                != QMessageBox.Yes:
            return
        shell_open(target, args)

    def _analyze(self) -> None:
        self._diag_done = True
        self.bn_title.setText("Analisando...")
        sys_snap = MonitorService.instance().latest
        net_snap = NetworkService.instance().latest
        run_task(advisor.analyze, sys_snap, net_snap, on_done=self._show_diag,
                 on_error=lambda e: self.bn_title.setText(f"Erro: {e}"))

    def _show_diag(self, result) -> None:
        b, suggestions = result
        self.bn_title.setText("Sem gargalo" if b.resource == "Nenhum" else f"{b.resource} ({b.level:.0f}%)")
        self.bn_detail.setText(b.detail)
        for res, (bar, v) in self.bn_bars.items():
            val = b.scores.get(res)
            bar.setValue(int((val or 0) * 10))
            v.setText("—" if val is None else f"{val:.0f}%")
        while self.sugg_box.count():
            it = self.sugg_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for sg in suggestions:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 4, 0, 4)
            dot = icon_label("", 10, obj="")
            dot.setStyleSheet(f"color: {SEV_COLOR.get(sg.severity)};")
            h.addWidget(dot, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = label(f"{sg.title}  ·  {SEV_TEXT.get(sg.severity)}", "Value")
            t.setStyleSheet("font-size: 11pt;")
            col.addWidget(t)
            col.addWidget(label(sg.detail, "Muted", wrap=True))
            h.addLayout(col, 1)
            if sg.action:
                btn = QPushButton(sg.action_label or "Abrir")
                btn.clicked.connect(lambda _=False, a=sg.action: self.window().navigate(a))
                h.addWidget(btn, 0, Qt.AlignTop)
            self.sugg_box.addWidget(w)
        self.sugg_card.title_label.setText(f"SUGESTÕES DE OTIMIZAÇÃO ({len(suggestions)})")
        self.relayout()

    # ================================================================ RELATÓRIOS
    def _build_reports(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        head = GlassCard("Relatório de desempenho", G.HISTORY)
        r = QHBoxLayout()
        self.period = Segmented([("24h", "24 horas"), ("7d", "7 dias"), ("30d", "30 dias")], "7d")
        self.period.changed.connect(lambda _k: self._generate())
        r.addWidget(self.period)
        r.addStretch(1)
        for text, fn, obj in (("Exportar HTML", self._export_html, "Primary"), ("Exportar CSV", self._export_csv, ""),
                              ("Abrir pasta", lambda: open_folder(str(reports.documents_dir())), "")):
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(fn)
            r.addWidget(b)
        head.add(r)
        self.rep_info = label("", "Muted", wrap=True)
        head.add(self.rep_info)
        lay.addWidget(head)

        self.rep_grid = ResponsiveGrid(min_col_width=200, max_cols=6, spacing=12)
        self.rep_cards = {}
        for key, title in (("cpu", "CPU média"), ("ram", "RAM média"), ("gpu", "GPU média"),
                           ("cpu_temp", "Temp. CPU média"), ("net", "Internet"), ("alerts", "Alertas")):
            c = GlassCard()
            wdg, v = stat_block(title)
            v.setObjectName("BigValue")
            v.setStyleSheet("font-size: 17pt;")
            c.add(wdg)
            sub = label("", "Faint", wrap=True)
            c.add(sub)
            self.rep_grid.add(c)
            self.rep_cards[key] = (v, sub)
        lay.addWidget(self.rep_grid)

        tables = ResponsiveGrid(min_col_width=440, max_cols=2)
        c1 = GlassCard("Programas que mais usaram CPU", G.CPU)
        self.top_cpu = make_table(["Programa", "Tempo de CPU", "Aberto por"], stretch=0)
        self.top_cpu.setMinimumHeight(300)
        c1.add(self.top_cpu)
        tables.add(c1)
        c2 = GlassCard("Programas que mais usaram memória", G.MEMORY)
        self.top_mem = make_table(["Programa", "Memória média", "Aberto por"], stretch=0)
        self.top_mem.setMinimumHeight(300)
        c2.add(self.top_mem)
        tables.add(c2)
        lay.addWidget(tables)
        lay.addWidget(label("O uso por programa é acumulado enquanto o PC Control Center está aberto (inclusive na "
                            "bandeja). Todos os dados ficam neste computador.", "Faint", wrap=True))
        return w

    def _generate(self) -> None:
        self.engine.usage.flush()   # inclui o uso dos últimos minutos
        self.rep_info.setText("Gerando...")
        run_task(reports.build_report, self.period.current(), on_done=self._show_report,
                 on_error=lambda e: self.rep_info.setText(f"Erro: {e}"))

    def _show_report(self, rep: dict) -> None:
        self._rep = rep
        st = rep["stats"]

        def f(col, unit="%"):
            s = st.get(col)
            return ("—", "sem dados") if not s else (
                f"{s['avg']:.0f}{unit}", f"pico {s['max']:.0f}{unit} · 95% abaixo de {s['p95']:.0f}{unit}")

        for key, unit in (("cpu", "%"), ("ram", "%"), ("gpu", "%"), ("cpu_temp", " °C")):
            v, sub = self.rep_cards[key]
            a, b = f(key, unit)
            v.setText(a)
            sub.setText(b)
        v, sub = self.rep_cards["net"]
        v.setText(fmt_bytes(rep["net"]["rx"]))
        sub.setText(f"baixados · {fmt_bytes(rep['net']['tx'])} enviados · {rep['drops']} queda(s)")
        v, sub = self.rep_cards["alerts"]
        v.setText(str(sum(n for k, n in rep["alerts"].items() if k != "report")))
        top = sorted(rep["alerts"].items(), key=lambda kv: -kv[1])[:2]
        sub.setText(" · ".join(f"{reports.ALERT_NAMES.get(k, k)}: {n}" for k, n in top) or "nenhum")
        hours = f"{rep['hours_monitored']:.1f}".replace(".", ",")
        self.rep_info.setText(
            f"{rep['label']}: {hours} h de dados (médias por minuto). "
            f"CPU acima de 80%: {rep['above']['cpu80']:.0f}% do tempo · RAM acima de 90%: "
            f"{rep['above']['ram90']:.0f}% do tempo.")

        def fill(table, rows, mem):
            table.setSortingEnabled(False)
            table.setRowCount(len(rows))
            for r, (app, cpu_s, m, secs) in enumerate(rows):
                vals = [app, fmt_bytes(m) if mem else f"{cpu_s / 60:.1f} min".replace(".", ","),
                        f"{secs / 3600:.1f} h".replace(".", ",")]
                for c, text in enumerate(vals):
                    table.setItem(r, c, QTableWidgetItem(text))

        fill(self.top_cpu, rep["top_cpu"], False)
        fill(self.top_mem, rep["top_mem"], True)

    def _export_html(self) -> None:
        rep = getattr(self, "_rep", None)
        if not rep:
            return
        path = reports.export_html(rep)
        os.startfile(path)

    def _export_csv(self) -> None:
        rep = getattr(self, "_rep", None)
        if not rep:
            return
        path = reports.export_csv(rep)
        open_folder(path)
