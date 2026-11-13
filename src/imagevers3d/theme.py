"""
theme.py - système de design de « Image vers 3D » : couleurs, tailles, feuille de style Qt, mouvement.

Les valeurs viennent de la maquette Figma et sont recopiées dans design/tokens.json (un test vérifie que les deux
sont identiques). Tout le reste de l'interface lit ses couleurs ici : aucune couleur n'est écrite ailleurs.

Principes (détail dans docs/DESIGN.md) :
  - un seul accent (ambre) : action principale, sélection, focus, progression ;
  - texte >= 4,5:1 (texte principal >= 7:1), contours de contrôles >= 3:1 ;
  - contrôles de 44 px, aucun texte sous 13 px (avant mise à l'échelle) ;
  - mouvement de 100 à 250 ms, coupé si Windows ou l'option « Réduire les animations » le demande.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

from . import paths

# --------------------------------------------------------------------------------------------------------------------
#  Couleurs (identiques à design/tokens.json et aux variables Figma « Couleurs », modes Sombre / Clair)
# --------------------------------------------------------------------------------------------------------------------
TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        "bg-app": "#12141A",
        "bg-viewport": "#0D0F13",
        "bg-panel": "#1A1D23",
        "bg-raised": "#232831",
        "bg-hover": "#2B313B",
        "bg-pressed": "#343B47",
        "border": "#303741",
        "border-strong": "#7C8695",
        "text": "#ECEEF2",
        "text-secondary": "#B0B8C4",
        "text-muted": "#98A1AE",
        "text-disabled": "#6B7482",
        "accent": "#F2A33A",
        "accent-hover": "#F7B55C",
        "accent-pressed": "#D98E26",
        "on-accent": "#1B1305",
        "accent-text": "#F5B351",
        "accent-soft": "#2E2616",
        "focus": "#F7B55C",
        "success": "#5BCB8E",
        "danger": "#F47C74",
        "warning": "#E7C84A",
        "info": "#73B8F0",
        "accent-ui": "#F2A33A",
    },
    "light": {
        "bg-app": "#F4F5F7",
        "bg-viewport": "#E6E9EE",
        "bg-panel": "#FFFFFF",
        "bg-raised": "#F0F2F5",
        "bg-hover": "#E6E9EE",
        "bg-pressed": "#DADFE6",
        "border": "#D5DAE1",
        "border-strong": "#6C7685",
        "text": "#16191F",
        "text-secondary": "#434C5A",
        "text-muted": "#566170",
        "text-disabled": "#8A93A0",
        "accent": "#F2A33A",
        "accent-hover": "#E8940F",
        "accent-pressed": "#CC7F08",
        "on-accent": "#1B1305",
        "accent-text": "#8A4F00",
        "accent-soft": "#FDF0DC",
        "focus": "#A85F00",
        "success": "#17703F",
        "danger": "#B3261E",
        "warning": "#7A5F00",
        "info": "#1B62A8",
        "accent-ui": "#A85F00",
    },
}

# Couleur de la matière quand le modèle n'a pas de couleurs propres (argile neutre, lisible sur chaque fond).
MESH_COLOR = {"dark": (0.82, 0.84, 0.88, 1.0), "light": (0.46, 0.50, 0.57, 1.0)}
THEME_MODES = ("dark", "light", "system")
TEXT_SCALES = (1.0, 1.15, 1.3)
FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf")
FONT_FALLBACKS = ("Inter", "Segoe UI", "Arial")


# --------------------------------------------------------------------------------------------------------------------
#  Contraste (sert aux tests et à la documentation)
# --------------------------------------------------------------------------------------------------------------------
def _luminance(color: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs « #RRGGBB »."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------------------------------------------------
#  Thème courant
# --------------------------------------------------------------------------------------------------------------------
class Theme:
    """Couleurs d'un mode (sombre ou clair) et échelle de texte. Les tailles passent par px()."""

    def __init__(self, mode: str = "dark", scale: float = 1.0) -> None:
        self.mode = "light" if mode == "light" else "dark"
        self.scale = scale if scale in TEXT_SCALES else 1.0
        self.colors = TOKENS[self.mode]

    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def __getitem__(self, key: str) -> str:
        return self.colors[key]

    def color(self, key: str, alpha: float = 1.0) -> QColor:
        c = QColor(self.colors[key])
        if alpha < 1.0:
            c.setAlphaF(alpha)
        return c


_current = Theme()


def current() -> Theme:
    return _current


def set_current(theme: Theme) -> None:
    global _current
    _current = theme


# --------------------------------------------------------------------------------------------------------------------
#  Mouvement
# --------------------------------------------------------------------------------------------------------------------
def system_prefers_reduced_motion() -> bool:
    """Windows : « Afficher les animations dans Windows » désactivé (SPI_GETCLIENTAREAANIMATION). Ailleurs : non."""
    if sys.platform != "win32":
        return False
    try:
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)  # type: ignore[attr-defined]
        return bool(ok) and enabled.value == 0
    except Exception:  # noqa: BLE001 - jamais bloquant
        return False


class Motion:
    """Interrupteur central des animations. Toute animation passe par ms() et enabled()."""

    system_reduced = False
    user_reduced = False

    @classmethod
    def refresh(cls, user_reduced: bool | None = None) -> None:
        cls.system_reduced = system_prefers_reduced_motion()
        if user_reduced is not None:
            cls.user_reduced = user_reduced

    @classmethod
    def enabled(cls) -> bool:
        return not (cls.system_reduced or cls.user_reduced)

    @classmethod
    def ms(cls, duration: int) -> int:
        return duration if cls.enabled() else 0


def ease_out() -> QEasingCurve:
    """cubic-bezier(0.23, 1, 0.32, 1) : départ rapide, arrivée douce."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))
    return curve


# --------------------------------------------------------------------------------------------------------------------
#  Polices
# --------------------------------------------------------------------------------------------------------------------
def load_fonts() -> str:
    """Enregistre Inter (fournie dans assets/fonts, licence OFL) et renvoie la famille à utiliser."""
    fonts_dir: Path = paths.ASSETS_DIR / "fonts"
    for name in FONT_FILES:
        font = fonts_dir / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    available = set(QFontDatabase.families())
    for family in FONT_FALLBACKS:
        if family in available:
            return family
    return QFont().family()


def make_font(family: str, theme: Theme, size: float = 14, weight: int = 400) -> QFont:
    font = QFont(family)
    font.setPixelSize(theme.px(size))
    font.setWeight(QFont.Weight(weight))
    try:  # chiffres de largeur fixe : les compteurs et durées ne « dansent » pas (Qt >= 6.7)
        font.setFeature(QFont.Tag("tnum"), 1)
    except Exception:  # noqa: BLE001
        pass
    return font


# --------------------------------------------------------------------------------------------------------------------
#  Feuille de style
# --------------------------------------------------------------------------------------------------------------------
def build_qss(t: Theme) -> str:
    """Feuille de style Qt complète pour un thème. Les widgets dessinés à la main lisent current() eux-mêmes."""
    c = t.colors
    p = t.px
    ctl, ctl_lg, r_ctl, r_panel = p(44), p(52), p(8), p(12)
    handle = "#FFFFFF" if t.mode == "light" else c["text"]  # poignée du curseur
    return f"""
QWidget {{ color: {c['text']}; selection-background-color: {c['accent']}; selection-color: {c['on-accent']}; }}
QMainWindow, QWidget#root {{ background: {c['bg-app']}; }}
QWidget#transparent, QScrollArea, QScrollArea > QWidget > QWidget#scrollBody {{ background: transparent; border: none; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['border-strong']};
    border-radius: {p(8)}px; padding: {p(6)}px {p(10)}px; font-size: {p(13)}px; }}

QFrame#topbar {{ background: {c['bg-panel']}; border: none; border-bottom: 1px solid {c['border']}; }}
QFrame#leftPanel {{ background: {c['bg-panel']}; border: none; border-right: 1px solid {c['border']}; }}
QFrame#footer {{ background: {c['bg-panel']}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#exportBar {{ background: {c['bg-panel']}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#logo {{ background: {c['bg-raised']}; border: 1px solid {c['border']}; border-radius: {r_ctl}px; }}
QFrame#viewport {{ background: {c['bg-viewport']}; border: none; }}
QLabel#viewerPlaceholder {{ color: {c['text-secondary']}; background: {c['bg-viewport']}; padding: {p(32)}px; }}
QFrame#chip {{ background: transparent; border: 1px solid {c['border']}; border-radius: {p(18)}px; }}
QFrame#floatBar {{ background: {c['bg-panel']}; border: 1px solid {c['border']}; border-radius: {r_panel}px; }}
QFrame#toast {{ background: {c['bg-raised']}; border: 1px solid {c['border-strong']}; border-radius: {r_panel}px; }}
QFrame#errorPanel, QFrame#gateCard {{ background: {c['bg-panel']}; border: 1px solid {c['border']}; border-radius: {r_panel}px; }}
QFrame#panelFooter {{ background: transparent; border: none; border-top: 1px solid {c['border']}; }}
QFrame#separator {{ background: {c['border']}; border: none; max-height: 1px; min-height: 1px; }}

QLabel#appName {{ font-size: {p(16)}px; font-weight: 600; }}
QLabel#h2 {{ font-size: {p(16)}px; font-weight: 600; }}
QLabel#title {{ font-size: {p(21)}px; font-weight: 600; }}
QLabel#display {{ font-size: {p(28)}px; font-weight: 600; }}
QLabel[role="label"] {{ font-size: {p(13)}px; font-weight: 500; }}
QLabel[role="secondary"] {{ color: {c['text-secondary']}; }}
QLabel[role="muted"] {{ color: {c['text-muted']}; font-size: {p(13)}px; }}
QLabel[role="caption"] {{ color: {c['text-secondary']}; font-size: {p(13)}px; }}
QLabel[role="danger"] {{ color: {c['danger']}; }}
QLabel#keycap {{ background: {c['bg-raised']}; border: 1px solid {c['border']}; border-radius: {p(6)}px;
    color: {c['text-secondary']}; font-size: {p(13)}px; padding: {p(1)}px {p(8)}px; }}
QLabel#infoPill {{ background: {c['bg-panel']}; border: 1px solid {c['border']}; border-radius: {p(16)}px;
    color: {c['text-secondary']}; font-size: {p(13)}px; padding: {p(5)}px {p(12)}px; }}

/* Boutons : un seul « primary » plein par vue */
QPushButton {{ min-height: {ctl}px; padding: 0 {p(16)}px; border-radius: {r_ctl}px; font-weight: 600;
    background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['border-strong']}; }}
QPushButton:hover {{ background: {c['bg-hover']}; }}
QPushButton:pressed {{ background: {c['bg-pressed']}; }}
QPushButton:focus {{ border: 2px solid {c['focus']}; padding: 0 {p(15)}px; }}
QPushButton:disabled {{ background: {c['bg-raised']}; color: {c['text-disabled']}; border: 1px solid {c['border']}; }}
QPushButton[kind="primary"] {{ background: {c['accent']}; color: {c['on-accent']}; border: 1px solid {c['accent']}; }}
QPushButton[kind="primary"]:hover {{ background: {c['accent-hover']}; border-color: {c['accent-hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {c['accent-pressed']}; border-color: {c['accent-pressed']}; }}
QPushButton[kind="primary"]:focus {{ border: 2px solid {c['focus']}; }}
QPushButton[kind="primary"]:disabled {{ background: {c['bg-raised']}; color: {c['text-disabled']};
    border: 1px solid {c['border']}; }}
QPushButton[kind="ghost"] {{ background: transparent; color: {c['text-secondary']}; border: 1px solid transparent; }}
QPushButton[kind="ghost"]:hover {{ background: {c['bg-hover']}; color: {c['text']}; }}
QPushButton[kind="ghost"]:pressed {{ background: {c['bg-pressed']}; color: {c['text']}; }}
QPushButton[kind="ghost"]:focus {{ border: 2px solid {c['focus']}; }}
QPushButton[kind="ghost"]:disabled {{ background: transparent; color: {c['text-disabled']}; border: 1px solid transparent; }}
QPushButton[align="left"] {{ text-align: left; }}
QPushButton[btnsize="lg"] {{ min-height: {ctl_lg}px; }}
QPushButton[btnsize="sm"] {{ min-height: {p(36)}px; max-height: {p(36)}px; padding: 0 {p(12)}px; border-radius: {p(18)}px; }}
QPushButton[kind="chip"] {{ background: {c['accent-soft']}; color: {c['accent-text']}; border: 1px solid {c['accent-ui']}; }}
QPushButton[kind="chip"]:hover {{ background: {c['bg-hover']}; }}
QPushButton[kind="chip"]:focus {{ border: 2px solid {c['focus']}; padding: 0 {p(11)}px; }}

QToolButton {{ min-width: {ctl}px; max-width: {ctl}px; min-height: {ctl}px; max-height: {ctl}px; border-radius: {r_ctl}px;
    background: transparent; border: 1px solid transparent; }}
QToolButton:hover {{ background: {c['bg-hover']}; }}
QToolButton:pressed {{ background: {c['bg-pressed']}; }}
QToolButton:checked {{ background: {c['accent-soft']}; border: 1px solid {c['accent-ui']}; }}
QToolButton:focus {{ border: 2px solid {c['focus']}; }}
QToolButton:disabled {{ background: transparent; border: 1px solid transparent; }}

/* Curseur */
QSlider {{ min-height: {p(28)}px; background: transparent; }}
QSlider::groove:horizontal {{ height: {p(4)}px; border-radius: {p(2)}px; background: {c['bg-pressed']}; }}
QSlider::sub-page:horizontal {{ height: {p(4)}px; border-radius: {p(2)}px; background: {c['accent-ui']}; }}
QSlider::handle:horizontal {{ width: {p(16)}px; height: {p(16)}px; margin: -{p(9)}px 0; border-radius: {p(10)}px;
    background: {handle}; border: {p(2)}px solid {c['accent-ui']}; }}
QSlider::handle:horizontal:hover {{ background: {c['accent-hover']}; }}
QSlider::handle:horizontal:focus {{ background: {c['accent-hover']}; border: {p(3)}px solid {c['focus']}; }}
QSlider::groove:horizontal:disabled {{ background: {c['bg-raised']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {c['text-disabled']}; }}
QSlider::handle:horizontal:disabled {{ background: {c['bg-raised']}; border-color: {c['border']}; }}

/* Listes et champs (options avancées) */
QLineEdit {{ min-height: {ctl}px; padding: 0 {p(12)}px; border-radius: {r_ctl}px; background: {c['bg-raised']};
    border: 1px solid {c['border-strong']}; color: {c['text']}; selection-background-color: {c['accent-soft']};
    selection-color: {c['text']}; }}
QLineEdit:hover {{ background: {c['bg-hover']}; }}
QLineEdit:focus {{ border: 2px solid {c['focus']}; padding: 0 {p(11)}px; }}
QLineEdit[invalid="true"] {{ border: 2px solid {c['danger']}; padding: 0 {p(11)}px; }}
QLineEdit:disabled {{ color: {c['text-disabled']}; border-color: {c['border']}; }}
QComboBox, QSpinBox {{ min-height: {ctl}px; padding: 0 {p(12)}px; border-radius: {r_ctl}px; background: {c['bg-raised']};
    border: 1px solid {c['border-strong']}; color: {c['text']}; }}
QComboBox:hover, QSpinBox:hover {{ background: {c['bg-hover']}; }}
QComboBox:focus, QSpinBox:focus {{ border: 2px solid {c['focus']}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {c['text-disabled']}; border-color: {c['border']}; }}
QComboBox::drop-down {{ border: none; width: {p(28)}px; }}
QComboBox QAbstractItemView {{ background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['border-strong']};
    selection-background-color: {c['accent-soft']}; selection-color: {c['text']}; outline: none; padding: {p(4)}px; }}

QScrollBar:vertical {{ background: transparent; width: {p(10)}px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border-strong']}; border-radius: {p(3)}px; min-height: {p(32)}px; margin: 0 {p(2)}px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical
    {{ background: none; height: 0; }}

QMenu {{ background: {c['bg-raised']}; border: 1px solid {c['border-strong']}; border-radius: {r_panel}px; padding: {p(6)}px; }}
QMenu::item {{ padding: {p(10)}px {p(16)}px; border-radius: {p(6)}px; }}
QMenu::item:selected {{ background: {c['bg-hover']}; }}
QMenu::item:disabled {{ color: {c['text-disabled']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: {p(4)}px {p(8)}px; }}
"""


# --------------------------------------------------------------------------------------------------------------------
#  Application du thème à toute l'application
# --------------------------------------------------------------------------------------------------------------------
class _Bus(QObject):
    """Prévient les widgets dessinés à la main (et les icônes) qu'ils doivent se redessiner."""

    changed = Signal()


bus = _Bus()
_font_family: str | None = None


class AppStyle(QProxyStyle):
    """Fusion + info-bulles plus vives (apparition rapide)."""

    def __init__(self) -> None:
        super().__init__("Fusion")

    def styleHint(self, hint, option: QStyleOption | None = None, widget: QWidget | None = None, returnData=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 450
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 1500
        return super().styleHint(hint, option, widget, returnData)


def system_mode() -> str:
    """« dark » ou « light » selon le réglage de Windows."""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"
    except Exception:  # noqa: BLE001
        return "dark"


def resolve_mode(preference: str) -> str:
    return system_mode() if preference == "system" else ("light" if preference == "light" else "dark")


def _palette(t: Theme) -> QPalette:
    """Palette Qt alignée sur les jetons : les parties non stylées (boîtes de dialogue, menus) restent cohérentes."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg-app",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "bg-raised",
        QPalette.ColorRole.AlternateBase: "bg-panel",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "bg-raised",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.ToolTipBase: "bg-raised",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "on-accent",
        QPalette.ColorRole.PlaceholderText: "text-muted",
        QPalette.ColorRole.Link: "accent-text",
    }
    for role, key in roles.items():
        palette.setColor(role, t.color(key))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, t.color("text-disabled"))
    return palette


def repaint_later(widget: QWidget) -> None:
    """Demande un repeignage. `QWidget.update` est appelée sur la classe de base : les vues (QListView, QTableView...) y
    superposent une surcharge `update(index)` qui, avec PySide6 6.9, refuse l'appel sans argument."""
    QWidget.update(widget)


def apply_theme(app: QApplication, mode: str = "dark", scale: float = 1.0) -> Theme:
    """Applique couleurs, police et feuille de style ; prévient les widgets personnalisés. `mode` : dark, light ou system."""
    global _font_family
    if _font_family is None:
        _font_family = load_fonts()
        app.setStyle(AppStyle())
    t = Theme(resolve_mode(mode), scale)
    set_current(t)
    app.setPalette(_palette(t))
    app.setFont(make_font(_font_family, t, 14, 400))
    app.setStyleSheet(build_qss(t))
    bus.changed.emit()
    for widget in app.allWidgets():
        repaint_later(widget)
    return t


def font_family() -> str:
    return _font_family or "Segoe UI"
