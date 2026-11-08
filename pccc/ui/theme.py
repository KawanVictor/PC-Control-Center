"""Sistema de temas: modo claro/escuro, cor de destaque e transparência dos cartões.

Toda a aparência é gerada a partir de alguns tokens, então trocar o tema em tempo real
é só reaplicar a folha de estilo (QSS) e avisar os gráficos via ``ThemeManager.changed``.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ..core.config import Settings

ACCENTS: dict[str, tuple[str, str]] = {
    # nome: (cor principal, cor secundária do gradiente)
    "cyan": ("#22d3ee", "#6366f1"),
    "violet": ("#a78bfa", "#ec4899"),
    "emerald": ("#34d399", "#06b6d4"),
    "amber": ("#fbbf24", "#f97316"),
    "rose": ("#fb7185", "#a855f7"),
    "blue": ("#60a5fa", "#22d3ee"),
}
ACCENT_LABELS = {"cyan": "Ciano", "violet": "Violeta", "emerald": "Esmeralda",
                 "amber": "Âmbar", "rose": "Rosa", "blue": "Azul"}

# Cores fixas por métrica (consistentes entre gráficos e cartões).
SERIES = {"cpu": "#22d3ee", "ram": "#a78bfa", "gpu": "#34d399", "disk": "#fbbf24",
          "down": "#38bdf8", "up": "#f472b6", "temp": "#fb7185"}

_PALETTES = {
    "dark": {
        "bg0": "#070a12", "bg1": "#0d1322", "text": "#e6eaf2", "muted": "#8b96ab",
        "faint": "#5b6578", "card": (255, 255, 255), "card_alpha": 0.045,
        "border": "rgba(255,255,255,0.08)", "hover": "rgba(255,255,255,0.06)",
        "input": "rgba(255,255,255,0.06)", "track": "rgba(255,255,255,0.08)",
        "grid": (255, 255, 255, 18),
    },
    "light": {
        "bg0": "#eef2f9", "bg1": "#f8fafc", "text": "#111827", "muted": "#5b6474",
        "faint": "#9aa3b2", "card": (255, 255, 255), "card_alpha": 0.70,
        "border": "rgba(15,23,42,0.08)", "hover": "rgba(15,23,42,0.05)",
        "input": "rgba(15,23,42,0.05)", "track": "rgba(15,23,42,0.08)",
        "grid": (15, 23, 42, 20),
    },
}


def rgba(hex_color: str, alpha: float) -> str:
    """'#22d3ee', 0.2 → 'rgba(34,211,238,0.200)'. (No QSS, '#RRGGBBAA' vira AARRGGBB.)"""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.3f})"


def icon_font_family() -> str:
    """Fonte de ícones nativa: Segoe Fluent Icons (Win11) ou Segoe MDL2 Assets (Win10)."""
    families = set(QFontDatabase.families())
    for fam in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if fam in families:
            return fam
    return "Segoe UI Symbol"


@dataclass
class Theme:
    mode: str
    accent_name: str
    transparency: float

    @property
    def dark(self) -> bool:
        return self.mode == "dark"

    @property
    def p(self) -> dict:
        return _PALETTES["dark" if self.dark else "light"]

    @property
    def accent(self) -> str:
        return ACCENTS.get(self.accent_name, ACCENTS["cyan"])[0]

    @property
    def accent2(self) -> str:
        return ACCENTS.get(self.accent_name, ACCENTS["cyan"])[1]

    def color(self, key: str) -> QColor:
        v = self.p[key]
        if isinstance(v, tuple):
            return QColor(*v)
        return QColor(v)

    def card_rgba(self, extra: float = 0.0) -> str:
        r, g, b = self.p["card"]
        # transparency=1 → cartões quase invisíveis; 0 → quase opacos
        base = self.p["card_alpha"]
        alpha = base + (1 - self.transparency) * (0.18 if self.dark else 0.30) + extra
        return f"rgba({r},{g},{b},{min(alpha, 1):.3f})"

    def stylesheet(self) -> str:
        p = self.p
        a, a2 = self.accent, self.accent2
        sel_text = "#0b1020" if self.dark else "#ffffff"
        return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; color: {p['text']}; }}
QWidget {{ background: transparent; font-size: 10pt; }}
QToolTip {{ background: {p['bg1']}; color: {p['text']}; border: 1px solid {p['border']};
            padding: 6px 8px; border-radius: 6px; }}

#Card {{ background: {self.card_rgba()}; border: 1px solid {p['border']}; border-radius: 16px; }}
#CardTitle {{ color: {p['muted']}; font-size: 9.5pt; font-weight: 600; letter-spacing: .3px; }}
#CardIcon {{ color: {a}; }}
#BigValue {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 24pt; font-weight: 600; }}
#Value {{ font-size: 13pt; font-weight: 600; }}
#Muted {{ color: {p['muted']}; }}
#Faint {{ color: {p['faint']}; font-size: 9pt; }}
#PageTitle {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 20pt; font-weight: 700; }}
#PageSubtitle {{ color: {p['muted']}; font-size: 10pt; }}
#SectionTitle {{ font-size: 11.5pt; font-weight: 600; }}
#Badge {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 9px;
          padding: 2px 8px; color: {p['muted']}; font-size: 8.5pt; }}
#BadgeAccent {{ background: transparent; border: 1px solid {a}; border-radius: 9px;
                padding: 2px 8px; color: {a}; font-size: 8.5pt; font-weight: 600; }}

/* --- Barra lateral --- */
#Sidebar {{ background: {self.card_rgba(-0.01)}; border-right: 1px solid {p['border']}; }}
#Logo {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 12.5pt; font-weight: 700; }}
#LogoSub {{ color: {p['muted']}; font-size: 8pt; }}
QPushButton#NavButton {{ text-align: left; background: transparent; border: none; border-radius: 10px;
              padding: 9px 12px; color: {p['muted']}; font-size: 10pt; }}
QPushButton#NavButton:hover {{ background: {p['hover']}; border: none; }}
QPushButton#NavButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                       stop:0 {rgba(a, 0.22)}, stop:1 {rgba(a2, 0.06)});
                      border: none; border-left: 3px solid {a}; }}

/* --- Controles --- */
QPushButton {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 9px;
               padding: 7px 14px; }}
QPushButton:hover {{ background: {p['hover']}; border-color: {a}; }}
QPushButton:pressed {{ background: {p['track']}; }}
QPushButton:disabled {{ color: {p['faint']}; }}
QPushButton#Primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {a}, stop:1 {a2});
                       color: {sel_text}; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ border: none; }}
QPushButton#Danger {{ border-color: #f43f5e; color: #fb7185; }}
QPushButton#Danger:disabled {{ border-color: {p['border']}; color: {p['faint']}; }}
QPushButton#Primary:disabled {{ background: {p['input']}; color: {p['faint']}; }}
QPushButton#Segment {{ border-radius: 8px; padding: 5px 12px; }}
QPushButton#Segment:checked {{ background: {a}; color: {sel_text}; border-color: {a}; }}
QPushButton#Swatch {{ border-radius: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0; }}
QPushButton#Tile {{ text-align: left; padding: 14px; border-radius: 14px; background: {self.card_rgba()}; }}
QPushButton#Tile:hover {{ background: {self.card_rgba(0.05)}; }}

QComboBox, QLineEdit, QSpinBox {{ background: {p['input']}; border: 1px solid {p['border']};
               border-radius: 8px; padding: 6px 10px; selection-background-color: {a}; }}
QComboBox:hover, QLineEdit:focus, QSpinBox:focus {{ border-color: {a}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['bg1']}; border: 1px solid {p['border']};
               selection-background-color: {a}; selection-color: {sel_text}; outline: none; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 38px; height: 20px; border-radius: 10px; background: {p['track']};
                        border: 1px solid {p['border']}; }}
QCheckBox::indicator:checked {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {a}, stop:1 {a2});
                                border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {p['track']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p['text']}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QProgressBar {{ background: {p['track']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ border-radius: 3px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {a}, stop:1 {a2}); }}

QTableWidget, QTreeWidget, QListWidget {{ background: transparent; border: none; outline: none;
               gridline-color: transparent; alternate-background-color: {p['hover']}; }}
QTableWidget::item, QTreeWidget::item {{ padding: 4px 6px; border: none; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
               background: {rgba(a, 0.19)}; color: {p['text']}; }}
QHeaderView::section {{ background: transparent; color: {p['muted']}; border: none;
               border-bottom: 1px solid {p['border']}; padding: 6px; font-weight: 600; font-size: 9pt; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['track']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {a}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['track']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QMenu {{ background: {p['bg1']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['hover']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 8px; }}
QMessageBox {{ background: {p['bg1']}; }}
QDialog {{ background: {p['bg1']}; }}
"""


class ThemeManager(QObject):
    """Mantém o tema atual e reaplica quando as configurações mudam."""

    changed = Signal(object)  # Theme
    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._settings = Settings.instance()
        self.theme = self._read()
        self._settings.changed.connect(self._on_setting)

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    def _read(self) -> Theme:
        s = self._settings
        return Theme(mode=s.get("appearance.mode", "dark"),
                     accent_name=s.get("appearance.accent", "cyan"),
                     transparency=float(s.get("appearance.transparency", 0.7)))

    def _on_setting(self, key: str, _value) -> None:
        if key.startswith("appearance") or key == "*":
            self.apply()

    def apply(self) -> None:
        self.theme = self._read()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(self.theme.stylesheet())
        self.changed.emit(self.theme)


def icon_font(size_pt: float = 12) -> QFont:
    f = QFont(icon_font_family())
    f.setPointSizeF(size_pt)
    return f
