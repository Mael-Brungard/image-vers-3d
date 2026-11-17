"""
theme.py - système de design de « ThreeRex » : couleurs, tailles, feuille de style Qt, mouvement.

L'identité est sombre : un noir violet profond, un orange incandescent (action principale, sélection, progression) et un
violet électrique (cadres, halos, éléments secondaires). Il n'y a volontairement pas de thème clair : les halos lumineux
n'ont de sens que sur fond sombre.

Les valeurs sont recopiées dans design/tokens.json (un test vérifie que les deux sont identiques). Tout le reste de
l'interface lit ses couleurs ici : aucune couleur n'est écrite ailleurs.

Principes (détail dans docs/DESIGN.md) :
  - texte >= 4,5:1 (texte principal >= 7:1), contours de contrôles >= 3:1, vérifiés par tests/test_theme.py ;
  - contrôles de 44 px, aucun texte sous 13 px (avant mise à l'échelle) ;
  - mouvement de 100 à 250 ms pour les réponses, plus lent pour l'ambiance ; tout est coupé si Windows ou l'option
    « Réduire les animations » le demande, et les effets décoratifs ont leur propre interrupteur.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPointF, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

from . import paths

# --------------------------------------------------------------------------------------------------------------------
#  Couleurs (identiques à design/tokens.json)
# --------------------------------------------------------------------------------------------------------------------
TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        # fonds : du plus profond (fenêtre) au plus proche (contrôles)
        "bg-deep": "#07060F",
        "bg-app": "#0C0A18",
        "bg-viewport": "#0A0916",
        "bg-panel": "#15122B",
        "bg-raised": "#1E1A3A",
        "bg-hover": "#29234D",
        "bg-pressed": "#342D5E",
        # contours
        "border": "#322B63",
        "border-strong": "#8A80BF",
        # textes
        "text": "#F4F1FF",
        "text-secondary": "#C9C2E6",
        "text-muted": "#A9A1D0",
        "text-disabled": "#6F6898",
        # orange incandescent : action principale, sélection
        "accent": "#FF7A1A",
        "accent-hover": "#FF9442",
        "accent-pressed": "#E5620A",
        "on-accent": "#1A0B02",
        "accent-text": "#FF9A4D",
        "accent-soft": "#3A2113",
        "accent-ui": "#FF7A1A",
        "focus": "#FFB27A",
        # violet électrique : cadres, halos, éléments secondaires
        "violet": "#8B5CF6",
        "violet-hover": "#A58AFF",
        "violet-text": "#B9A3FF",
        "violet-soft": "#2B2255",
        "violet-deep": "#5B2DD1",
        # états
        "success": "#4ADE9A",
        "danger": "#FF8080",
        "warning": "#FFD166",
        "info": "#7CC4FF",
    },
}

# Couleur de la matière quand le modèle n'a pas de couleurs propres (argile neutre, lisible sur chaque fond).
MESH_COLOR = {"dark": (0.86, 0.84, 0.92, 1.0)}
THEME_MODES = ("dark",)
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
    """Couleurs du thème (sombre) et échelle de texte. Les tailles passent par px()."""

    def __init__(self, mode: str = "dark", scale: float = 1.0) -> None:
        self.mode = "dark"  # un seul thème : l'argument reste pour ne pas casser les appelants
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
    effects_off = False  # « Effets visuels » désactivés dans les réglages : plus de halos, de particules ni de lueurs animées

    @classmethod
    def refresh(cls, user_reduced: bool | None = None, effects_off: bool | None = None) -> None:
        cls.system_reduced = system_prefers_reduced_motion()
        if user_reduced is not None:
            cls.user_reduced = user_reduced
        if effects_off is not None:
            cls.effects_off = effects_off

    @classmethod
    def enabled(cls) -> bool:
        """Les mouvements qui répondent à un geste (glissement d'un curseur, apparition d'un message...)."""
        return not (cls.system_reduced or cls.user_reduced)

    @classmethod
    def ambient(cls) -> bool:
        """Les mouvements d'ambiance (halos qui respirent, particules, robot qui cligne des yeux). Seuls ceux-là peuvent
        être coupés à part avec l'option « Effets visuels »."""
        return cls.enabled() and not cls.effects_off

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
def chevron_path(t: Theme, direction: str = "down") -> str:
    """Chemin d'une petite flèche (PNG, « down » ou « up ») pour les listes déroulantes et les compteurs : Qt ne la dessine
    plus quand le contrôle est stylé. Le fichier est écrit une fois dans le dossier temporaire ; renvoie "" si l'écriture échoue."""
    try:
        import tempfile

        from . import icons

        folder = Path(tempfile.gettempdir()) / "threerex-ui"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"chevron-{direction}-{t.colors['text-secondary'][1:]}-{t.px(16)}.png"
        if not target.exists():
            icons.pixmap(f"chevron-{direction}", t["text-secondary"], t.px(16), 1.0).save(str(target), "PNG")
        return target.as_posix()
    except Exception:  # noqa: BLE001 - la flèche est décorative : jamais bloquant
        return ""


def build_qss(t: Theme) -> str:
    """Feuille de style Qt complète. Les widgets dessinés à la main (panneaux, boutons lumineux, logo...) lisent current()."""
    c = t.colors
    p = t.px
    ctl, ctl_lg, r_ctl, r_panel = p(44), p(56), p(10), p(14)

    def rgba(key: str, alpha: float) -> str:
        q = QColor(c[key])
        return f"rgba({q.red()}, {q.green()}, {q.blue()}, {round(alpha * 255)})"

    chevron = chevron_path(t)
    chevron_up = chevron_path(t, "up")
    arrow = f"QComboBox::down-arrow {{ image: url({chevron}); width: {p(16)}px; height: {p(16)}px; }}" if chevron else ""
    if chevron and chevron_up:  # compteurs : deux flèches empilées à droite
        arrow += f"""
QSpinBox::up-arrow {{ image: url({chevron_up}); width: {p(14)}px; height: {p(14)}px; }}
QSpinBox::down-arrow {{ image: url({chevron}); width: {p(14)}px; height: {p(14)}px; }}"""
    return f"""
QWidget {{ color: {c['text']}; selection-background-color: {c['accent']}; selection-color: {c['on-accent']}; }}
QMainWindow, QWidget#root {{ background: {c['bg-app']}; }}
QWidget#transparent, QScrollArea, QScrollArea > QWidget > QWidget#scrollBody {{ background: transparent; border: none; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['violet']};
    border-radius: {p(8)}px; padding: {p(6)}px {p(10)}px; font-size: {p(13)}px; }}

QFrame#topbar, QFrame#leftPanel, QFrame#footer, QFrame#panelFooter {{ background: transparent; border: none; }}
QFrame#exportBar {{ background: {rgba('bg-panel', 0.92)}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#viewport {{ background: transparent; border: none; }}
QLabel#viewerPlaceholder {{ color: {c['text-secondary']}; background: {c['bg-viewport']}; padding: {p(32)}px; }}
QFrame#chip {{ background: {rgba('bg-panel', 0.9)}; border: 1px solid {c['border']}; border-radius: {p(18)}px; }}
QFrame#floatBar {{ background: {rgba('bg-panel', 0.88)}; border: 1px solid {c['border']}; border-radius: {r_panel}px; }}
QFrame#toast {{ background: {c['bg-raised']}; border: 1px solid {c['violet']}; border-radius: {r_panel}px; }}
QFrame#errorPanel {{ background: {c['bg-panel']}; border: 1px solid {c['danger']}; border-radius: {r_panel}px; }}
QDialog#printDialog {{ background: {c['bg-panel']}; }}
QFrame#separator {{ background: {c['border']}; border: none; max-height: 1px; min-height: 1px; }}

QLabel#appName {{ font-size: {p(16)}px; font-weight: 600; }}
QLabel#h2 {{ font-size: {p(16)}px; font-weight: 600; }}
QLabel#panelTitle {{ font-size: {p(15)}px; font-weight: 600; color: {c['text']}; }}
QLabel#title {{ font-size: {p(21)}px; font-weight: 600; }}
QLabel#display {{ font-size: {p(28)}px; font-weight: 600; }}
QLabel[role="label"] {{ font-size: {p(13)}px; font-weight: 500; color: {c['text-secondary']}; }}
QLabel[role="secondary"] {{ color: {c['text-secondary']}; }}
QLabel[role="muted"] {{ color: {c['text-muted']}; font-size: {p(13)}px; }}
QLabel[role="caption"] {{ color: {c['text-secondary']}; font-size: {p(13)}px; }}
QLabel[role="danger"] {{ color: {c['danger']}; }}
QLabel#keycap {{ background: {c['bg-raised']}; border: 1px solid {c['border-strong']}; border-radius: {p(6)}px;
    color: {c['text-secondary']}; font-size: {p(13)}px; padding: {p(1)}px {p(8)}px; }}
QLabel#infoPill {{ background: {rgba('bg-panel', 0.88)}; border: 1px solid {c['border']}; border-radius: {p(16)}px;
    color: {c['text-secondary']}; font-size: {p(13)}px; padding: {p(5)}px {p(12)}px; }}
QLabel#badge {{ background: {c['accent-soft']}; border: 1px solid {c['accent']}; border-radius: {p(9)}px;
    color: {c['accent-text']}; font-size: {p(13)}px; font-weight: 600; padding: {p(1)}px {p(9)}px; }}
QLabel#badge[tone="violet"] {{ background: {c['violet-soft']}; border: 1px solid {c['violet']}; border-radius: {p(9)}px;
    color: {c['violet-text']}; font-size: {p(13)}px; font-weight: 600; padding: {p(1)}px {p(9)}px; }}

/* Boutons : un seul « primary » plein par vue */
QPushButton {{ min-height: {ctl}px; padding: 0 {p(16)}px; border-radius: {r_ctl}px; font-weight: 600;
    background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['border-strong']}; }}
QPushButton:hover {{ background: {c['bg-hover']}; border-color: {c['violet-hover']}; }}
QPushButton:pressed {{ background: {c['bg-pressed']}; }}
QPushButton:focus {{ border: 2px solid {c['focus']}; padding: 0 {p(15)}px; }}
QPushButton:disabled {{ background: {c['bg-raised']}; color: {c['text-disabled']}; border: 1px solid {c['border']}; }}
QPushButton[kind="primary"] {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['accent-hover']}, stop:1 {c['accent']});
    color: {c['on-accent']}; border: 1px solid {c['accent']}; }}
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
QPushButton[kind="ghost"][align="left"] {{ padding-left: 0; }}
QPushButton[btnsize="lg"] {{ min-height: {ctl_lg}px; }}

QToolButton {{ min-width: {ctl}px; max-width: {ctl}px; min-height: {ctl}px; max-height: {ctl}px; border-radius: {r_ctl}px;
    background: transparent; border: 1px solid transparent; }}
QToolButton:hover {{ background: {c['bg-hover']}; border-color: {c['violet']}; }}
QToolButton:pressed {{ background: {c['bg-pressed']}; }}
QToolButton:checked {{ background: {c['accent-soft']}; border: 1px solid {c['accent-ui']}; }}
QToolButton:focus {{ border: 2px solid {c['focus']}; }}
QToolButton:disabled {{ background: transparent; border: 1px solid transparent; }}
QToolButton#modeBtn {{ min-width: 0; max-width: {p(1000)}px; padding: 0 {p(12)}px; font-weight: 600; color: {c['text-secondary']}; }}
QToolButton#modeBtn:hover, QToolButton#modeBtn:checked {{ color: {c['text']}; }}
QToolButton#modeBtn:disabled {{ color: {c['text-disabled']}; }}

/* Curseur */
QSlider {{ min-height: {p(28)}px; background: transparent; }}
QSlider::groove:horizontal {{ height: {p(4)}px; border-radius: {p(2)}px; background: {c['bg-pressed']}; }}
QSlider::sub-page:horizontal {{ height: {p(4)}px; border-radius: {p(2)}px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['violet']}, stop:1 {c['accent-ui']}); }}
QSlider::handle:horizontal {{ width: {p(16)}px; height: {p(16)}px; margin: -{p(9)}px 0; border-radius: {p(10)}px;
    background: {c['text']}; border: {p(2)}px solid {c['accent-ui']}; }}
QSlider::handle:horizontal:hover {{ background: {c['accent-hover']}; }}
QSlider::handle:horizontal:focus {{ background: {c['accent-hover']}; border: {p(3)}px solid {c['focus']}; }}
QSlider::groove:horizontal:disabled {{ background: {c['bg-raised']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {c['text-disabled']}; }}
QSlider::handle:horizontal:disabled {{ background: {c['bg-raised']}; border-color: {c['border']}; }}

/* Listes et champs */
QComboBox, QSpinBox {{ min-height: {ctl}px; padding: 0 {p(12)}px; border-radius: {r_ctl}px; background: {c['bg-raised']};
    border: 1px solid {c['border-strong']}; color: {c['text']}; }}
QComboBox:hover, QSpinBox:hover {{ background: {c['bg-hover']}; border-color: {c['violet-hover']}; }}
QComboBox:focus, QSpinBox:focus {{ border: 2px solid {c['focus']}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {c['text-disabled']}; border-color: {c['border']}; }}
QComboBox::drop-down {{ border: none; width: {p(32)}px; }}
QSpinBox {{ padding: 0 {p(34)}px 0 0; }}
QSpinBox QLineEdit {{ background: transparent; border: none; padding: 0; margin: 0; color: {c['text']}; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: {p(28)}px; border: none; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {r_ctl}px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {r_ctl}px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c['bg-pressed']}; }}
{arrow}
QComboBox QAbstractItemView {{ background: {c['bg-raised']}; color: {c['text']}; border: 1px solid {c['violet']};
    selection-background-color: {c['violet-soft']}; selection-color: {c['text']}; outline: none; padding: {p(4)}px; }}

QScrollBar:vertical {{ background: transparent; width: {p(10)}px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border-strong']}; border-radius: {p(3)}px; min-height: {p(32)}px; margin: 0 {p(2)}px; }}
QScrollBar::handle:vertical:hover {{ background: {c['violet-hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical
    {{ background: none; height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: {p(10)}px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['border-strong']}; border-radius: {p(3)}px; min-width: {p(32)}px; margin: {p(2)}px 0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal
    {{ background: none; width: 0; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {rgba('violet', 0.45)}; }}

QMenu {{ background: {c['bg-raised']}; border: 1px solid {c['violet']}; border-radius: {r_panel}px; padding: {p(6)}px; }}
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


def resolve_mode(preference: str = "dark") -> str:
    """ThreeRex n'a qu'un thème (sombre) : toute préférence enregistrée, y compris « clair » ou « système », donne « dark »."""
    return "dark"


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
    """Applique couleurs, police et feuille de style ; prévient les widgets personnalisés. `mode` est ignoré (un seul thème)."""
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
