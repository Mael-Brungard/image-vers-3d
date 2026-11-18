"""
fx.py - identité visuelle de « ThreeRex » : mascotte T-Rex, logo, robot assistant, panneaux angulaires, bouton lumineux,
puces, onglets, fond, particules.

Tout est dessiné en vectoriel avec QPainter (aucune image) : net à toutes les tailles et tous les écrans, et les couleurs
viennent de theme.py. La mascotte et le robot sont des dessins originaux.

Règles de mouvement (docs/DESIGN.md) :
  - un seul minuteur partagé (Clock), 30 images par seconde au plus, arrêté quand la fenêtre n'est pas active ;
  - les effets d'ambiance (halos qui respirent, particules, clignement des yeux) se coupent avec « Effets visuels » ou
    « Réduire les animations » ; ils laissent alors une image fixe, jamais un trou ;
  - aucune animation n'est liée à un calcul : elles ne ralentissent ni la génération ni la manipulation du modèle.
"""

from __future__ import annotations

import math
import random
import time
import weakref
from typing import Any

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QLayout,
    QLayoutItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .theme import Motion, current, font_family, make_font


# --------------------------------------------------------------------------------------------------------------------
#  Horloge partagée
# --------------------------------------------------------------------------------------------------------------------
class Clock(QObject):
    """Un seul minuteur (30 i/s) pour toutes les animations d'ambiance. Les widgets s'y abonnent à l'affichage (watch) et
    s'en retirent au masquage (unwatch) : une fenêtre cachée ou inactive ne coûte rien."""

    INTERVAL_MS = 33
    require_active = True  # les tests désactivent cette règle : la plateforme « offscreen » ne devient pas toujours active
    _instance: Clock | None = None

    def __init__(self) -> None:
        super().__init__()
        self._subs: dict[int, tuple[weakref.ref, int, bool]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._count = 0

    @classmethod
    def instance(cls) -> Clock:
        if cls._instance is None:
            cls._instance = Clock()
        return cls._instance

    @staticmethod
    def now() -> float:
        return time.monotonic()

    @classmethod
    def t(cls, ambient: bool = True) -> float:
        """Temps d'animation en secondes ; 0 (pose fixe) quand le mouvement correspondant est coupé."""
        allowed = Motion.ambient() if ambient else Motion.enabled()
        return time.monotonic() if allowed else 0.0

    @classmethod
    def watch(cls, widget: QWidget, every: int = 1, ambient: bool = True) -> None:
        """Repeint `widget` tous les `every` tops d'horloge tant qu'il est visible."""
        clock = cls.instance()
        clock._subs[id(widget)] = (weakref.ref(widget), max(every, 1), ambient)
        if not clock._timer.isActive():
            clock._timer.start()

    @classmethod
    def unwatch(cls, widget: QWidget) -> None:
        clock = cls.instance()
        clock._subs.pop(id(widget), None)
        if not clock._subs:
            try:
                clock._timer.stop()
            except RuntimeError:  # arrêt du programme : le minuteur Qt est déjà détruit
                pass

    def _tick(self) -> None:
        self._count += 1
        if self.require_active and QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        dead = []
        for key, (ref, every, ambient) in self._subs.items():
            widget = ref()
            if widget is None:
                dead.append(key)
                continue
            if self._count % every or not widget.isVisible():
                continue
            if not (Motion.ambient() if ambient else Motion.enabled()):
                continue
            QWidget.update(widget)
        for key in dead:
            self._subs.pop(key, None)
        if not self._subs:
            self._timer.stop()

    @classmethod
    def active_count(cls) -> int:
        return len(cls.instance()._subs)


class Animated(QWidget):
    """Widget qui s'abonne à l'horloge tant qu'il est visible."""

    EVERY = 1
    AMBIENT = True

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        Clock.watch(self, self.EVERY, self.AMBIENT)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        Clock.unwatch(self)


# --------------------------------------------------------------------------------------------------------------------
#  Géométrie angulaire
# --------------------------------------------------------------------------------------------------------------------
def chamfer_path(rect: QRectF, tl: float = 0.0, tr: float = 0.0, br: float = 0.0, bl: float = 0.0) -> QPainterPath:
    """Rectangle dont les coins sont coupés en biais (tl : haut gauche, tr : haut droit, br : bas droit, bl : bas gauche)."""
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    path = QPainterPath(QPointF(x0 + tl, y0))
    path.lineTo(x1 - tr, y0)
    path.lineTo(x1, y0 + tr)
    path.lineTo(x1, y1 - br)
    path.lineTo(x1 - br, y1)
    path.lineTo(x0 + bl, y1)
    path.lineTo(x0, y1 - bl)
    path.lineTo(x0, y0 + tl)
    path.closeSubpath()
    return path


def with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def glow_stroke(p: QPainter, path: QPainterPath, color: QColor, width: float, strength: float = 1.0) -> None:
    """Lueur autour d'un contour : trois traits de plus en plus larges et transparents (pas d'effet de flou, donc léger)."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    for k, alpha in ((3.0, 0.05), (2.0, 0.08), (1.3, 0.14)):
        p.setPen(QPen(with_alpha(color, alpha * strength), width * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.MiterJoin))
        p.drawPath(path)


# --------------------------------------------------------------------------------------------------------------------
#  Mascotte T-Rex (dessin original, repère 100 x 100, tête de profil tournée vers la droite)
# --------------------------------------------------------------------------------------------------------------------
def _poly(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    path.closeSubpath()
    return path


_MASCOT: dict[str, Any] | None = None


def mascot_shapes() -> dict[str, Any]:
    """Formes de la mascotte (calculées une fois) : crâne, mâchoire, dents, œil, narine, cicatrice."""
    global _MASCOT
    if _MASCOT is not None:
        return _MASCOT
    skull = _poly([
        (6, 46), (14, 30), (11, 14), (26, 22), (29, 7), (42, 16), (52, 12), (61, 16), (67, 23), (80, 24), (92, 30), (98, 39),
        (97, 48),
        # dessous de la mâchoire haute : dents (pointes vers le bas) et creux
        (92, 49), (91, 59), (86, 50), (83, 60), (77, 51), (74, 60), (68, 52), (65, 60), (59, 53), (52, 55), (45, 58),
        (36, 57), (27, 61), (19, 72), (5, 63),
    ])
    # mâchoire basse : ouverte, charnière près du coin de la bouche
    a, b = QPointF(44, 63), QPointF(91, 82)
    jaw = _poly([(28, 54), (44, 63), (91, 82), (93, 89), (84, 94), (62, 91), (46, 85), (32, 76), (24, 64)])
    cavity = _poly([(36, 57), (90, 58), (82, 78), (44, 63)])
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    nx, ny = uy, -ux  # perpendiculaire, vers le haut
    teeth = QPainterPath()
    for k in (0.28, 0.46, 0.64, 0.82):
        cx, cy = a.x() + dx * k, a.y() + dy * k
        base0 = QPointF(cx - ux * 3.2, cy - uy * 3.2 + 0.6)
        base1 = QPointF(cx + ux * 3.2, cy + uy * 3.2 + 0.6)
        tip = QPointF(cx + nx * 8.5 - ux * 0.5, cy + ny * 8.5 - uy * 0.5)
        teeth.addPolygon([base0, tip, base1])
        teeth.closeSubpath()
    upper_teeth = QPainterPath()
    for tip_x, tip_y in ((91, 59), (83, 60), (74, 60), (65, 60)):
        upper_teeth.addPolygon([QPointF(tip_x - 4.2, 51), QPointF(tip_x, tip_y + 0.5), QPointF(tip_x + 3.2, 51)])
        upper_teeth.closeSubpath()
    eye = _poly([(59, 30), (73, 27), (71, 33), (62, 35)])
    nostril = QPainterPath()
    nostril.addEllipse(QPointF(91.5, 36), 2.3, 1.3)
    scar = QPainterPath(QPointF(40, 36))
    scar.lineTo(51, 41)
    scar.lineTo(48, 46)
    scar.lineTo(58, 50)
    _MASCOT = {"skull": skull, "jaw": jaw, "lower_teeth": teeth, "upper_teeth": upper_teeth, "eye": eye,
               "nostril": nostril, "scar": scar, "cavity": cavity}
    return _MASCOT


def paint_mark(p: QPainter, rect: QRectF, glow: float = 1.0, mono: QColor | None = None) -> None:
    """Dessine la mascotte dans `rect` (carré conseillé). `glow` 0..1 : intensité de la lueur ; `mono` : une seule couleur."""
    t = current()
    shapes = mascot_shapes()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = min(rect.width(), rect.height())
    p.translate(rect.center().x() - size / 2, rect.center().y() - size / 2)
    p.scale(size / 100.0, size / 100.0)
    if glow > 0 and mono is None:
        halo = QRadialGradient(QPointF(54, 52), 62)
        halo.setColorAt(0.0, with_alpha(t.color("accent"), 0.30 * glow))
        halo.setColorAt(0.55, with_alpha(t.color("violet"), 0.16 * glow))
        halo.setColorAt(1.0, with_alpha(t.color("violet"), 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(54, 52), 62, 62)
    if mono is not None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mono)
        p.drawPath(shapes["skull"])
        p.drawPath(shapes["jaw"])
        p.restore()
        return
    # intérieur de la bouche, puis mâchoire basse (violet) : dessinées avant le crâne, qui les recouvre à la charnière
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(with_alpha(t.color("bg-deep"), 0.78))
    p.drawPath(shapes["cavity"])
    jaw_fill = QLinearGradient(QPointF(40, 60), QPointF(70, 96))
    jaw_fill.setColorAt(0.0, t.color("violet-hover"))
    jaw_fill.setColorAt(0.55, t.color("violet"))
    jaw_fill.setColorAt(1.0, t.color("violet-deep"))
    p.setPen(QPen(with_alpha(t.color("violet-hover"), 0.9), 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.MiterJoin))
    p.setBrush(QBrush(jaw_fill))
    p.drawPath(shapes["jaw"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFF4E8"))
    p.drawPath(shapes["lower_teeth"])
    # crâne (orange incandescent)
    skull_fill = QLinearGradient(QPointF(30, 6), QPointF(70, 76))
    skull_fill.setColorAt(0.0, QColor("#FFC766"))
    skull_fill.setColorAt(0.42, t.color("accent"))
    skull_fill.setColorAt(1.0, QColor("#E2440A"))
    p.setPen(QPen(QColor("#FFD9A8"), 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
    p.setBrush(QBrush(skull_fill))
    p.drawPath(shapes["skull"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFF4E8"))
    p.drawPath(shapes["upper_teeth"])
    # détails : cicatrice, narine, œil
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(with_alpha(QColor("#6B1D00"), 0.55), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.MiterJoin))
    p.drawPath(shapes["scar"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(with_alpha(QColor("#4A1200"), 0.85))
    p.drawPath(shapes["nostril"])
    p.setBrush(QColor("#1A0B02"))
    p.drawPath(shapes["eye"])
    eye_glow = QRadialGradient(QPointF(66, 31), 7)
    eye_glow.setColorAt(0.0, QColor("#FFF3B0"))
    eye_glow.setColorAt(1.0, with_alpha(QColor("#FFD166"), 0.0))
    p.setBrush(QBrush(eye_glow))
    p.drawEllipse(QPointF(66, 31), 7, 7)
    p.setBrush(QColor("#FFF3B0"))
    p.drawPath(_poly([(61, 31), (71, 29), (69, 32.5), (63, 33.5)]))
    p.restore()


# --------------------------------------------------------------------------------------------------------------------
#  Logo : mascotte + « ThreeRex » en italique
# --------------------------------------------------------------------------------------------------------------------
def wordmark_path(height: float, family: str | None = None) -> tuple[QPainterPath, QPainterPath, float]:
    """Contours du mot « ThreeRex » (partie claire « Three », partie orange « Rex »), inclinés à droite ; renvoie aussi la
    largeur. Le texte est dessiné en contours : le gras et l'italique ne dépendent pas des graisses de la police."""
    font = QFont(family or font_family())
    font.setPixelSize(max(int(height), 8))
    font.setWeight(QFont.Weight.Bold)
    fm = QFontMetrics(font)
    base_y = height * 0.82
    first, second = QPainterPath(), QPainterPath()
    first.addText(0, base_y, font, "Three")
    second.addText(fm.horizontalAdvance("Three") + height * 0.02, base_y, font, "Rex")
    shear = QTransform()
    shear.translate(0, base_y)
    shear.shear(-0.2, 0)
    shear.translate(0, -base_y)
    first, second = shear.map(first), shear.map(second)
    width = first.boundingRect().united(second.boundingRect()).right()
    return first, second, width


class Logo(QWidget):
    """Mascotte + nom + accroche. Hauteur fixe (en pixels du thème), largeur calculée d'après le texte."""

    def __init__(self, height: int = 44, tagline: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = height
        self._tagline_full = "De l'image au modèle 3D" if tagline else ""
        self._tagline = self._tagline_full
        self.setAccessibleName("ThreeRex")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.bus.changed.connect(self._refit)
        self._refit()

    def set_compact(self, compact: bool) -> None:
        """Fenêtre étroite : l'accroche disparaît, la mascotte et le nom restent."""
        wanted = "" if compact else self._tagline_full
        if wanted != self._tagline:
            self._tagline = wanted
            self._refit()

    def _metrics(self) -> tuple[int, float, float]:
        t = current()
        h = t.px(self._base)
        mark = h
        word_h = h * 0.5
        return h, mark, word_h

    def _refit(self) -> None:
        t = current()
        h, mark, word_h = self._metrics()
        _a, _b, word_w = wordmark_path(word_h)
        tag_w = QFontMetrics(make_font(font_family(), t, 13, 500)).horizontalAdvance(self._tagline) if self._tagline else 0
        self.setFixedSize(int(mark + t.px(10) + max(word_w, tag_w) + t.px(6)), h)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        h, mark, word_h = self._metrics()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_mark(p, QRectF(0, 0, mark, mark), glow=0.9)
        first, second, _w = wordmark_path(word_h)
        x = mark + t.px(8)
        y = (h - word_h) / 2 - (t.px(7) if self._tagline else 0)
        p.save()
        p.translate(x, y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("text"))
        p.drawPath(first)
        grad = QLinearGradient(QPointF(first.boundingRect().right(), 0), QPointF(first.boundingRect().right() + word_h * 1.5, word_h))
        grad.setColorAt(0.0, QColor("#FFB259"))
        grad.setColorAt(1.0, t.color("accent"))
        p.setBrush(QBrush(grad))
        p.drawPath(second)
        p.restore()
        if self._tagline:
            p.setFont(make_font(font_family(), t, 13, 500))
            p.setPen(t.color("text-muted"))
            p.drawText(QRectF(x, y + word_h + t.px(1), self.width() - x, t.px(18)),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._tagline)


# --------------------------------------------------------------------------------------------------------------------
#  Robot assistant (dessin original, repère 64 x 64)
# --------------------------------------------------------------------------------------------------------------------
def paint_robot(p: QPainter, rect: QRectF, blink: float = 0.0, bob: float = 0.0, glow: float = 1.0) -> None:
    """Petit robot de face. `blink` 0..1 : paupières fermées ; `bob` : décalage vertical en unités de 64 (±1,5 au plus)."""
    t = current()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = min(rect.width(), rect.height()) * 0.92  # marge : le halo de l'antenne et le balancement ne touchent jamais le bord
    p.translate(rect.center().x() - size / 2, rect.center().y() - size / 2 + bob * size / 64.0)
    p.scale(size / 64.0, size / 64.0)
    outline = QPen(t.color("violet-hover"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
    # antenne
    p.setPen(QPen(t.color("violet-hover"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(32, 11), QPointF(32, 5))
    if glow > 0:
        halo = QRadialGradient(QPointF(32, 4.5), 5)  # rayon 5 : au plus haut du balancement, le halo reste dans le cadre
        halo.setColorAt(0.0, with_alpha(t.color("accent"), 0.55 * glow))
        halo.setColorAt(1.0, with_alpha(t.color("accent"), 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(32, 4.5), 5, 5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(t.color("accent-hover"))
    p.drawEllipse(QPointF(32, 4.5), 2.3, 2.3)
    # oreilles
    p.setBrush(t.color("violet-deep"))
    p.drawRoundedRect(QRectF(4.5, 19, 5, 11), 1.8, 1.8)
    p.drawRoundedRect(QRectF(54.5, 19, 5, 11), 1.8, 1.8)
    # corps
    body = _poly([(17, 42), (47, 42), (43, 59), (21, 59)])
    body_fill = QLinearGradient(QPointF(32, 42), QPointF(32, 60))
    body_fill.setColorAt(0.0, t.color("violet"))
    body_fill.setColorAt(1.0, t.color("violet-deep"))
    p.setPen(outline)
    p.setBrush(QBrush(body_fill))
    p.drawPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(t.color("accent-hover"))
    p.drawEllipse(QPointF(32, 50.5), 2.6, 2.6)
    p.setBrush(t.color("violet-deep"))
    p.drawRoundedRect(QRectF(9.5, 44, 5, 11), 1.8, 1.8)
    p.drawRoundedRect(QRectF(49.5, 44, 5, 11), 1.8, 1.8)
    # tête
    head = chamfer_path(QRectF(10, 10, 44, 32), 6, 6, 6, 6)
    head_fill = QLinearGradient(QPointF(32, 10), QPointF(32, 42))
    head_fill.setColorAt(0.0, t.color("violet-hover"))
    head_fill.setColorAt(1.0, t.color("violet"))
    p.setPen(outline)
    p.setBrush(QBrush(head_fill))
    p.drawPath(head)
    # visière et yeux
    p.setPen(QPen(with_alpha(t.color("violet-text"), 0.6), 1.0))
    p.setBrush(t.color("bg-deep"))
    p.drawRoundedRect(QRectF(15, 16, 34, 20), 5, 5)
    open_h = 10.0 * (1.0 - 0.9 * max(0.0, min(1.0, blink)))
    p.setPen(Qt.PenStyle.NoPen)
    for cx in (24.5, 39.5):
        if glow > 0:
            eye_halo = QRadialGradient(QPointF(cx, 26), 8)
            eye_halo.setColorAt(0.0, with_alpha(t.color("accent"), 0.35 * glow))
            eye_halo.setColorAt(1.0, with_alpha(t.color("accent"), 0.0))
            p.setBrush(QBrush(eye_halo))
            p.drawEllipse(QPointF(cx, 26), 8, 8)
        p.setBrush(t.color("accent-hover"))
        p.drawRoundedRect(QRectF(cx - 3.2, 26 - open_h / 2, 6.4, open_h), 3.0, 3.0)
    p.restore()


class Robot(Animated):
    """Robot assistant : respire doucement et cligne des yeux de temps en temps (immobile si les effets sont coupés)."""

    EVERY = 2  # 15 images par seconde suffisent pour un si petit dessin
    BOB = 1.2  # amplitude du balancement, en unités de 64 (paint_robot garde la marge pour ±1,5)
    clicked = Signal()

    def __init__(self, size: int = 56, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = size
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clique pour une astuce")
        self.setAccessibleName("Assistant ThreeRex")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.bus.changed.connect(self._refit)
        self._refit()

    def _refit(self) -> None:
        s = current().px(self._base)
        self.setFixedSize(s, s)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = Clock.t()
        bob = math.sin(t * 2.1) * self.BOB if t else 0.0
        cycle = (t % 4.2) if t else 9.0
        blink = 0.0
        if cycle < 0.16:
            blink = 1.0 - abs(cycle - 0.08) / 0.08
        p = QPainter(self)
        paint_robot(p, QRectF(self.rect()), blink=blink, bob=bob, glow=1.0 if Motion.effects_off is False else 0.6)


# --------------------------------------------------------------------------------------------------------------------
#  Fond de la fenêtre
# --------------------------------------------------------------------------------------------------------------------
_backdrop_cache: dict[tuple[int, int], QPixmap] = {}


def backdrop_pixmap(size: QSize) -> QPixmap:
    """Fond de la fenêtre : noir violet, une lueur violette en haut à droite, une braise orange en bas à gauche et quelques
    points d'étoile. Mis en cache par taille (une seule peinture quand la fenêtre change de taille)."""
    key = (size.width(), size.height())
    if key in _backdrop_cache:
        return _backdrop_cache[key]
    if len(_backdrop_cache) > 6:
        _backdrop_cache.clear()
    t = current()
    w, h = max(size.width(), 1), max(size.height(), 1)
    pix = QPixmap(w, h)
    pix.fill(t.color("bg-app"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QLinearGradient(QPointF(0, 0), QPointF(0, h))
    base.setColorAt(0.0, t.color("bg-app"))
    base.setColorAt(1.0, t.color("bg-deep"))
    p.fillRect(0, 0, w, h, QBrush(base))
    big = max(w, h)
    violet = QRadialGradient(QPointF(w * 0.86, h * 0.02), big * 0.62)
    violet.setColorAt(0.0, with_alpha(t.color("violet"), 0.26))
    violet.setColorAt(1.0, with_alpha(t.color("violet"), 0.0))
    p.fillRect(0, 0, w, h, QBrush(violet))
    ember = QRadialGradient(QPointF(w * 0.04, h * 1.02), big * 0.5)
    ember.setColorAt(0.0, with_alpha(t.color("accent"), 0.16))
    ember.setColorAt(1.0, with_alpha(t.color("accent"), 0.0))
    p.fillRect(0, 0, w, h, QBrush(ember))
    rng = random.Random(7)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(70):
        x, y = rng.random() * w, rng.random() * h
        r = 0.6 + rng.random() * 1.0
        p.setBrush(with_alpha(t.color("violet-text"), 0.10 + rng.random() * 0.22))
        p.drawEllipse(QPointF(x, y), r, r)
    p.end()
    _backdrop_cache[key] = pix
    return pix


class Backdrop(QWidget):
    """Widget racine : peint le fond immersif derrière tout le reste."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        theme.bus.changed.connect(self._reset)

    def _reset(self) -> None:
        _backdrop_cache.clear()
        QWidget.update(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.drawPixmap(0, 0, backdrop_pixmap(self.size()))


# --------------------------------------------------------------------------------------------------------------------
#  Panneau angulaire
# --------------------------------------------------------------------------------------------------------------------
class Panel(QFrame):
    """Panneau à coins coupés (haut gauche et bas droit), fond translucide, contour dégradé violet vers orange et lueur douce.
    `accent` : « violet » (défaut), « orange » ou « mixte ». Le contenu se place avec un layout comme dans un QFrame."""

    def __init__(self, accent: str = "violet", parent: QWidget | None = None, margin: int = 16, cut: int = 14) -> None:
        super().__init__(parent)
        self._accent = accent
        self._margin = margin
        self._cut = cut
        self._glow = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        theme.bus.changed.connect(self._remargin)
        self._remargin()

    def _remargin(self) -> None:
        t = current()
        m = t.px(self._margin)
        self.setContentsMargins(m, m, m, m)
        self.update()

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def vbox(self, spacing: int = 10):
        """Disposition verticale du panneau : sans marge propre (les marges sont celles du panneau)."""
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(spacing)
        return box

    def border_colors(self) -> tuple[QColor, QColor]:
        t = current()
        if self._accent == "orange":
            return t.color("accent"), t.color("violet-deep")
        if self._accent == "mixte":
            return t.color("violet-hover"), t.color("accent")
        return t.color("violet-hover"), t.color("violet-deep")

    def shape(self, inset: float = 1.0) -> QPainterPath:
        c = current().px(self._cut)
        return chamfer_path(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), tl=c, br=c)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self.shape(2.0)
        first, second = self.border_colors()
        if self._glow > 0 and Motion.effects_off is False:
            glow_stroke(p, path, first, 2.2, 0.7)
        fill = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        fill.setColorAt(0.0, with_alpha(t.color("bg-panel"), 0.95))
        fill.setColorAt(1.0, with_alpha(t.color("bg-app"), 0.92))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        # reflet en haut : un fin liseré clair qui s'efface vers la droite
        shine = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        shine.setColorAt(0.0, with_alpha(first, 0.55))
        shine.setColorAt(1.0, with_alpha(first, 0.0))
        p.setPen(QPen(QBrush(shine), 1.0))
        p.drawLine(QPointF(t.px(self._cut) + 4, 3.0), QPointF(self.width() * 0.8, 3.0))
        border = QLinearGradient(QPointF(0, 0), QPointF(self.width(), self.height()))
        border.setColorAt(0.0, first)
        border.setColorAt(1.0, second)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(border), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
        p.drawPath(path)
        # repère orange sur le coin coupé en haut à gauche
        c = t.px(self._cut)
        p.setPen(QPen(t.color("accent"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(2.0 + c * 0.25, 2.0 + c * 0.75), QPointF(2.0 + c * 0.75, 2.0 + c * 0.25))


# --------------------------------------------------------------------------------------------------------------------
#  Bouton lumineux
# --------------------------------------------------------------------------------------------------------------------
class GlowButton(QPushButton):
    """Bouton principal à coins coupés. `kind="primary"` : orange incandescent qui respire doucement ; sinon contour
    violet. Se comporte comme un QPushButton (text, icon, kind, setEnabled, click...). La lueur déborde du corps du bouton :
    la taille réserve cette marge, la zone cliquable reste celle du corps."""

    GLOW = 12  # marge de lueur du grand bouton, en pixels du thème ; le bouton bas en réserve moins (8)

    def __init__(self, text: str = "", kind: str | None = "primary", parent: QWidget | None = None, tall: bool = True,
                 icon_after: bool = True) -> None:
        super().__init__(text, parent)
        if kind:
            self.setProperty("kind", kind)
        self._tall = tall
        self._icon_after = icon_after
        self._hover = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.bus.changed.connect(self.updateGeometry)

    def _body_height(self) -> int:
        return current().px(60 if self._tall else 48)

    def _glow(self) -> int:
        return current().px(self.GLOW if self._tall else 8)

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        font = make_font(font_family(), t, 17 if self._tall else 15, 700)
        width = QFontMetrics(font).horizontalAdvance(self.text()) + t.px(36) + 2 * self._glow()
        if not self.icon().isNull():
            width += t.px(34)
        return QSize(width, self._body_height() + 2 * self._glow())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _body(self) -> QRectF:
        g = self._glow()
        return QRectF(g, g, self.width() - 2 * g, self.height() - 2 * g)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self._body().contains(QPointF(pos))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = 1.0
        QWidget.update(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = 0.0
        QWidget.update(self)
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        Clock.watch(self, 2, True)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        Clock.unwatch(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        primary = (self.property("kind") or "") == "primary"
        body = self._body()
        pressed = self.isDown()
        if pressed:
            body = body.translated(0, 1)
        cut = t.px(14 if self._tall else 10)
        path = chamfer_path(body, tl=cut, br=cut)
        breathe = 0.5 + 0.5 * math.sin(Clock.t() * 2.4) if Motion.ambient() else 0.6

        if enabled:
            tint = t.color("accent") if primary else t.color("violet")
            strength = (0.55 + 0.35 * breathe) if primary else 0.35
            strength += 0.35 * self._hover + (0.0 if Motion.effects_off else 0.0)
            g = self._glow()
            for k, alpha in ((1.0, 0.10), (0.72, 0.14), (0.44, 0.20)):
                spread = g * k
                p.setPen(QPen(with_alpha(tint, alpha * strength), spread, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.MiterJoin))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

        if not enabled:
            fill, edge, text_color = t.color("bg-raised"), t.color("border"), t.color("text-disabled")
            p.setBrush(fill)
        elif primary:
            grad = QLinearGradient(body.topLeft(), body.bottomRight())
            top = t.color("accent-pressed") if pressed else (t.color("accent-hover") if self._hover else QColor("#FFA040"))
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, t.color("accent-pressed") if pressed else t.color("accent"))
            p.setBrush(QBrush(grad))
            edge, text_color = QColor("#FFD2A6"), t.color("on-accent")
        else:
            grad = QLinearGradient(body.topLeft(), body.bottomRight())
            grad.setColorAt(0.0, t.color("violet-soft"))
            grad.setColorAt(1.0, t.color("bg-raised"))
            p.setBrush(QBrush(grad))
            edge = t.color("violet-hover") if (self._hover or pressed) else t.color("violet")
            text_color = t.color("text")
        p.setPen(QPen(edge, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
        p.drawPath(path)

        # texte et icône, centrés ensemble
        font = make_font(font_family(), t, 17 if self._tall else 15, 700)
        p.setFont(font)
        text = self.text()
        fm = QFontMetrics(font)
        icon_size = t.px(22)
        has_icon = not self.icon().isNull()
        gap = t.px(10) if has_icon else 0
        pad = t.px(18)
        avail = int(body.width() - 2 * pad - (icon_size + gap if has_icon else 0))
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(avail, 10))
        text_w = fm.horizontalAdvance(shown)
        total = text_w + (icon_size + gap if has_icon else 0)
        x0 = body.left() + (body.width() - total) / 2
        mode = QIcon_mode(enabled)
        pix = self.icon().pixmap(QSize(icon_size, icon_size), mode) if has_icon else None
        y = body.top() + (body.height() - icon_size) / 2
        if has_icon and not self._icon_after and pix is not None:
            p.drawPixmap(QPointF(x0, y), pix)
            x0 += icon_size + gap
        p.setPen(text_color)
        p.drawText(QRectF(x0, body.top(), text_w + 2, body.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   shown)
        if has_icon and self._icon_after and pix is not None:
            p.drawPixmap(QPointF(x0 + text_w + gap, y), pix)

        if self.hasFocus():
            ring = chamfer_path(body.adjusted(-3, -3, 3, 3), tl=cut + 3, br=cut + 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawPath(ring)


def QIcon_mode(enabled: bool):  # noqa: N802
    from PySide6.QtGui import QIcon

    return QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled


# --------------------------------------------------------------------------------------------------------------------
#  Puces (options cochables) et disposition qui passe à la ligne
# --------------------------------------------------------------------------------------------------------------------
class Chip(QAbstractButton):
    """Puce cochable : un réglage oui/non présenté comme une étiquette. Cochée : fond orange sombre, contour orange et coche."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)
        self._hover = False
        theme.bus.changed.connect(self.updateGeometry)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def _font(self) -> QFont:
        return make_font(font_family(), current(), 14, 600 if self.isChecked() else 500)

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        fm = QFontMetrics(make_font(font_family(), t, 14, 600))
        return QSize(fm.horizontalAdvance(self.text()) + t.px(14) + t.px(20) + t.px(14) + 8, t.px(40))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        QWidget.update(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        QWidget.update(self)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        on = self.isChecked()
        box = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = box.height() / 2
        if not enabled:
            fill, edge, color = t.color("bg-raised"), t.color("border"), t.color("text-disabled")
        elif on:
            fill, edge, color = t.color("accent-soft"), t.color("accent-ui"), t.color("text")
        else:
            fill = t.color("bg-hover") if self.isDown() else t.color("bg-raised")
            edge = t.color("violet-hover") if self._hover else t.color("border-strong")
            color = t.color("text-secondary") if not self._hover else t.color("text")
        p.setPen(QPen(edge, 1.5))
        p.setBrush(fill)
        p.drawRoundedRect(box, radius, radius)
        p.setFont(self._font())
        text_rect = box.adjusted(t.px(14) + (t.px(20) if on else 0), 0, -t.px(12), 0)
        p.setPen(color)
        shown = QFontMetrics(p.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        if on:
            mark = icons.pixmap("check", t["accent-text" if enabled else "text-disabled"], t.px(16))
            p.drawPixmap(QPointF(box.left() + t.px(12), (self.height() - t.px(16)) / 2), mark)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius + 1, radius + 1)


class FlowLayout(QLayout):
    """Dispose les éléments de gauche à droite et passe à la ligne quand la largeur manque (pas de débordement)."""

    def __init__(self, parent: QWidget | None = None, h_spacing: int = 8, v_spacing: int = 8, centered: bool = False) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = h_spacing
        self._v = v_spacing
        self._centered = centered
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows: list[list[tuple[QLayoutItem, QSize]]] = [[]]
        row_w = 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if item.hasHeightForWidth():  # panneau à texte qui passe à la ligne : sa hauteur dépend de sa largeur
                hint.setHeight(max(hint.height(), item.heightForWidth(hint.width())))
            if rows[-1] and row_w + hint.width() > area.width():
                rows.append([])
                row_w = 0
            rows[-1].append((item, hint))
            row_w += hint.width() + self._h
        y = area.y()
        for row in rows:
            if not row:
                continue
            row_h = max(hint.height() for _item, hint in row)
            used = sum(hint.width() for _item, hint in row) + self._h * (len(row) - 1)
            x = area.x() + (max(area.width() - used, 0) // 2 if self._centered else 0)
            if not test_only:
                for item, hint in row:
                    item.setGeometry(QRect(x, y, hint.width(), hint.height()))
                    x += hint.width() + self._h
            y += row_h + self._v
        return max(y - self._v, area.y()) - rect.y() + m.bottom()


# --------------------------------------------------------------------------------------------------------------------
#  Onglets de la barre du haut
# --------------------------------------------------------------------------------------------------------------------
class TabBar(QWidget):
    """Onglets « Image vers 3D / Mes créations / Paramètres » : texte et icône, soulignement lumineux orange vers violet."""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs: list[tuple[str, str]] = []
        self._index = 0
        self._hover = -1
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Sections")
        theme.bus.changed.connect(self.updateGeometry)

    def addTab(self, text: str, icon_name: str) -> int:  # noqa: N802
        self._tabs.append((text, icon_name))
        self.updateGeometry()
        self.update()
        return len(self._tabs) - 1

    def count(self) -> int:
        return len(self._tabs)

    def tabText(self, index: int) -> str:  # noqa: N802
        return self._tabs[index][0]

    def currentIndex(self) -> int:  # noqa: N802
        return self._index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._tabs) and index != self._index:
            self._index = index
            self.update()
            self.currentChanged.emit(index)

    def _tab_font(self, active: bool) -> QFont:
        return make_font(font_family(), current(), 15, 600 if active else 500)

    def _widths(self) -> list[int]:
        t = current()
        fm = QFontMetrics(self._tab_font(True))
        return [fm.horizontalAdvance(text) + t.px(20) + t.px(8) + 2 * t.px(14) for text, _ in self._tabs]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(sum(self._widths()), current().px(48))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _rects(self) -> list[QRectF]:
        rects, x = [], 0.0
        for w in self._widths():
            rects.append(QRectF(x, 0, w, self.height()))
            x += w
        return rects

    def _at(self, pos) -> int:
        for i, r in enumerate(self._rects()):
            if r.contains(QPointF(pos)):
                return i
        return -1

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        i = self._at(event.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        i = self._at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and i >= 0:
            self.setCurrentIndex(i)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(event.key())
        if step:
            self.setCurrentIndex(min(max(self._index + step, 0), len(self._tabs) - 1))
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, (rect, (text, icon_name)) in enumerate(zip(self._rects(), self._tabs)):
            active = i == self._index
            color = "text" if active else ("text" if i == self._hover else "text-secondary")
            if i == self._hover and not active:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(t.color("violet"), 0.14))
                p.drawRoundedRect(rect.adjusted(2, 6, -2, -8), t.px(8), t.px(8))
            icon = icons.pixmap(icon_name, t["accent-text" if active else color], t.px(20))
            x = rect.left() + t.px(14)
            p.drawPixmap(QPointF(x, (self.height() - t.px(20)) / 2 - 1), icon)
            p.setFont(self._tab_font(active))
            p.setPen(t.color(color))
            p.drawText(QRectF(x + t.px(28), 0, rect.width() - t.px(28) - t.px(14), self.height() - 2),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            if active:
                bar = QRectF(rect.left() + t.px(10), self.height() - 5, rect.width() - t.px(20), 3)
                grad = QLinearGradient(bar.topLeft(), bar.topRight())
                grad.setColorAt(0.0, t.color("accent"))
                grad.setColorAt(1.0, t.color("violet"))
                if not Motion.effects_off:
                    for k, alpha in ((7, 0.08), (4.5, 0.14), (2.5, 0.22)):
                        p.setPen(QPen(with_alpha(t.color("accent"), alpha), k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                        p.drawLine(bar.left() + 2, bar.center().y(), bar.right() - 2, bar.center().y())
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(grad))
                p.drawRoundedRect(bar, 1.5, 1.5)
        if self.hasFocus():
            r = self._rects()[self._index].adjusted(2, 4, -2, -6)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawRoundedRect(r, t.px(8), t.px(8))


# --------------------------------------------------------------------------------------------------------------------
#  Particules lumineuses
# --------------------------------------------------------------------------------------------------------------------
class ParticleField(Animated):
    """Fine poussière lumineuse (violet et orange) sur le visualiseur. Transparente aux clics. Deux modes : « orbit » (autour
    du modèle : les grains tournent doucement sur des ellipses) et « drift » (flottent vers le haut). Se met en pause pendant
    que l'utilisateur manipule le modèle (pause_for) : les effets ne ralentissent jamais un geste."""

    EVERY = 2
    COUNT = 34

    def __init__(self, mode: str = "orbit", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._mode = mode
        rng = random.Random(11)
        self._grains = [
            {
                "a": rng.random() * math.tau, "r": 0.30 + rng.random() * 0.26, "w": (0.10 + rng.random() * 0.22) * rng.choice((-1, 1)),
                "tilt": 0.28 + rng.random() * 0.4, "size": 1.3 + rng.random() * 2.2, "warm": rng.random() < 0.45,
                "x": rng.random(), "y": rng.random(), "v": 0.012 + rng.random() * 0.03, "ph": rng.random() * math.tau,
            }
            for _ in range(self.COUNT)
        ]
        self._paused_until = 0.0

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def pause_for(self, seconds: float = 0.7) -> None:
        self._paused_until = time.monotonic() + seconds

    def paused(self) -> bool:
        return time.monotonic() < self._paused_until

    def paintEvent(self, event) -> None:  # noqa: N802
        if Motion.effects_off:
            return
        t = current()
        clock = Clock.t()
        if self.paused():
            return  # pendant un geste : rien n'est repeint, la scène 3D garde toute la fluidité
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h * 0.47
        span = min(w, h)
        p.setPen(Qt.PenStyle.NoPen)
        for g in self._grains:
            twinkle = 0.55 + 0.45 * math.sin(clock * 1.6 + g["ph"])
            if self._mode == "orbit":
                ang = g["a"] + clock * g["w"]
                x = cx + math.cos(ang) * g["r"] * span * 1.25
                y = cy + math.sin(ang) * g["r"] * span * g["tilt"] + math.sin(clock * 0.7 + g["ph"]) * 5
            else:
                x = (g["x"] * w + math.sin(clock * 0.3 + g["ph"]) * 14) % w
                y = (g["y"] - clock * g["v"]) % 1.0 * h
            color = t.color("accent-hover") if g["warm"] else t.color("violet-hover")
            r = g["size"] * (t.scale if t.scale > 1 else 1.0)
            p.setBrush(with_alpha(color, 0.10 * twinkle))
            p.drawEllipse(QPointF(x, y), r * 3.2, r * 3.2)
            p.setBrush(with_alpha(color, 0.75 * twinkle))
            p.drawEllipse(QPointF(x, y), r * 0.9, r * 0.9)


# --------------------------------------------------------------------------------------------------------------------
#  Reconstruction pendant le calcul
# --------------------------------------------------------------------------------------------------------------------
class ReconstructionView(Animated):
    """Animation du calcul : l'image que le modèle reçoit se « reconstruit » en nuage de points reliés, du bas vers le haut,
    sous une ligne de balayage orange, en boucle. C'est une animation d'attente : elle ne représente PAS l'avancement réel
    (le moteur n'en donne pas) et n'affiche aucun pourcentage. Sans mouvement (réglage Windows ou « Réduire les
    animations »), elle montre l'image déjà reconstruite, fixe."""

    EVERY = 1
    AMBIENT = False  # indicateur de travail : suit « Réduire les animations », pas l'interrupteur des effets d'ambiance
    GRID = 58
    CYCLE = 4.4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dots: list[tuple[int, int, int, int, int]] = []  # colonne, ligne, r, g, b
        self._cells: set[tuple[int, int]] = set()
        self._gw = self._gh = 1
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(60)
        self.setAccessibleName("Reconstruction du modèle en cours")

    def has_source(self) -> bool:
        return bool(self._dots)

    def set_source(self, image) -> None:
        """`image` : image PIL (celle que reçoit le moteur) ou None."""
        self._dots, self._cells = [], set()
        if image is None:
            self.update()
            return
        import numpy as np
        from PIL import Image

        rgba = image.convert("RGBA")
        scale = self.GRID / max(rgba.size)
        small = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))), Image.Resampling.BILINEAR)
        arr = np.asarray(small)
        rgb, alpha = arr[..., :3].astype(int), arr[..., 3]
        if alpha.min() < 250:  # vraie transparence : le fond est déjà retiré
            mask = alpha > 40
        else:  # fond uni : on le déduit des quatre coins
            corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
            background = np.median(corners, axis=0)
            mask = np.abs(rgb - background).sum(axis=2) > 60
        coverage = float(mask.mean())
        if coverage < 0.02 or coverage > 0.98:
            mask = np.ones_like(mask)
        self._gh, self._gw = mask.shape
        ys, xs = np.nonzero(mask)
        self._dots = [(int(x), int(y), int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2])) for x, y in zip(xs, ys)]
        self._cells = {(x, y) for x, y, *_ in self._dots}
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._dots:
            return
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clock = Clock.t(ambient=False)
        pad = t.px(14)
        avail = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        cell = min(avail.width() / self._gw, avail.height() / self._gh)
        area = QRectF(0, 0, cell * self._gw, cell * self._gh)
        area.moveCenter(avail.center())
        if clock:
            phase = (clock % self.CYCLE) / self.CYCLE
            raw = min(phase / 0.78, 1.0)
            progress = raw * raw * (3 - 2 * raw)
            fade = 1.0 - max(0.0, (phase - 0.92) / 0.08)
        else:
            progress, fade = 0.78, 1.0
        front = 1.0 - progress  # les lignes situées sous ce seuil (normalisé) sont reconstruites
        dot = max(1.6, cell * 0.64)
        violet = t.color("violet-hover")

        # orbite : un grand anneau incliné dont les tirets tournent
        ring = QPen(with_alpha(violet, 0.5 * fade), 1.2)
        ring.setDashPattern([2.0, 5.0])
        ring.setDashOffset(-clock * 12.0)
        p.setPen(ring)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(area.center(), area.width() * 0.62, area.height() * 0.16 + t.px(10))

        # liaisons entre points voisins reconstruits
        lines = []
        for x, y, *_ in self._dots:
            if y / self._gh < front:
                continue
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if (nx, ny) in self._cells and ny / self._gh >= front:
                    lines.append(QPointF(area.left() + (x + 0.5) * cell, area.top() + (y + 0.5) * cell))
                    lines.append(QPointF(area.left() + (nx + 0.5) * cell, area.top() + (ny + 0.5) * cell))
        if lines:
            p.setPen(QPen(with_alpha(violet, 0.34 * fade), 0.8))
            p.drawLines(lines)

        # points : fantômes au-dessus du front, couleur de l'image en dessous, braise sur le front lui-même
        p.setPen(Qt.PenStyle.NoPen)
        ember = t.color("accent-hover")
        for x, y, r, g, b in self._dots:
            cx = area.left() + (x + 0.5) * cell
            cy = area.top() + (y + 0.5) * cell
            ny = y / self._gh
            if ny < front:
                p.setBrush(with_alpha(violet, 0.16 * fade))
                p.drawRect(QRectF(cx - dot * 0.3, cy - dot * 0.3, dot * 0.6, dot * 0.6))
                continue
            if ny - front < 0.035 and clock:
                p.setBrush(with_alpha(ember, 0.95 * fade))
            else:
                p.setBrush(with_alpha(QColor(r, g, b), 0.95 * fade))
            wobble = math.sin(ny * 9.0 + clock * 2.4) * cell * 0.18 * (1.0 - progress) if clock else 0.0
            p.drawRect(QRectF(cx - dot / 2 + wobble, cy - dot / 2, dot, dot))

        # ligne de balayage
        if clock and 0.0 < progress < 1.0:
            y = area.top() + area.height() * front
            band = QLinearGradient(QPointF(0, y - t.px(20)), QPointF(0, y + 2))
            band.setColorAt(0.0, with_alpha(ember, 0.0))
            band.setColorAt(1.0, with_alpha(ember, 0.38 * fade))
            p.fillRect(QRectF(area.left() - 6, y - t.px(20), area.width() + 12, t.px(20) + 2), QBrush(band))
            p.setPen(QPen(with_alpha(ember, fade), 2))
            p.drawLine(QPointF(area.left() - 6, y), QPointF(area.right() + 6, y))
        # repères de visée
        arm = min(t.px(18), area.width() / 4)
        p.setPen(QPen(t.color("accent"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        r = area.adjusted(-5, -5, 5, 5)
        for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * arm, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * arm))


# --------------------------------------------------------------------------------------------------------------------
#  Bulle de l'assistant
# --------------------------------------------------------------------------------------------------------------------
def wrap_elide(text: str, fm: QFontMetrics, width: int, max_lines: int) -> list[str]:
    """Coupe `text` en lignes de `width` pixels au plus ; au-delà de `max_lines`, la dernière ligne se termine par « … »."""
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        trial = f"{current_line} {word}".strip()
        if fm.horizontalAdvance(trial) <= width:
            current_line = trial
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    if len(lines) > max_lines:
        tail = " ".join(lines[max_lines - 1:])
        lines = [*lines[: max_lines - 1], fm.elidedText(tail, Qt.TextElideMode.ElideRight, width)]
    # Une ligne que horizontalAdvance() (arrondi à l'entier) juge assez courte n'est jamais raccourcie : elidedText() compare
    # des largeurs décimales et coupait « à tort » une ligne qui tombait à moins d'un pixel de la largeur disponible
    # (échec constaté sur la CI Linux, selon la machine et la police).
    return [line if fm.horizontalAdvance(line) <= width else fm.elidedText(line, Qt.TextElideMode.ElideRight, width) for line in lines]


class Bubble(QWidget):
    """Bulle de dialogue (queue à droite, vers le robot) : une astuce courte sur deux lignes au plus. Le texte complet est
    aussi l'info-bulle et le nom accessible, au cas où la place manque."""

    LINES = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.bus.changed.connect(self.updateGeometry)

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def text(self) -> str:
        return self._text

    def _font(self) -> QFont:
        return make_font(font_family(), current(), 13, 500)

    def _height(self) -> int:
        t = current()
        return QFontMetrics(self._font()).lineSpacing() * self.LINES + 2 * t.px(9)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(current().px(360), self._height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(current().px(120), self._height())

    def _text_width(self) -> int:
        t = current()
        return int(self.width() - t.px(8) - 3 - 2 * t.px(12))

    def is_elided(self) -> bool:
        """Vrai si le texte ne tient pas en deux lignes à la largeur actuelle (la fin serait remplacée par « … »)."""
        lines = wrap_elide(self._text, QFontMetrics(self._font()), self._text_width(), self.LINES)
        return " ".join(lines) != " ".join(self._text.split())

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tail = t.px(8)
        body = QRectF(1.5, 1.5, self.width() - tail - 3, self.height() - 3)
        path = chamfer_path(body, tl=t.px(8), br=t.px(8))
        mid = body.center().y()
        tip = QPainterPath()
        tip.moveTo(body.right() - 0.5, mid - t.px(7))
        tip.lineTo(body.right() + tail, mid)
        tip.lineTo(body.right() - 0.5, mid + t.px(7))
        tip.closeSubpath()
        bubble = path.united(tip)
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        fill.setColorAt(0.0, with_alpha(t.color("violet-soft"), 0.95))
        fill.setColorAt(1.0, with_alpha(t.color("bg-panel"), 0.95))
        p.setBrush(QBrush(fill))
        p.setPen(QPen(t.color("violet"), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
        p.drawPath(bubble)
        font = self._font()
        p.setFont(font)
        p.setPen(t.color("text"))
        fm = QFontMetrics(font)
        pad = t.px(12)
        lines = wrap_elide(self._text, fm, int(body.width() - 2 * pad), self.LINES)
        block = fm.lineSpacing() * len(lines)
        y = body.top() + (body.height() - block) / 2
        for line in lines:
            p.drawText(QRectF(body.left() + pad, y, body.width() - 2 * pad, fm.lineSpacing()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, line)
            y += fm.lineSpacing()


# --------------------------------------------------------------------------------------------------------------------
#  Panneau repliable
# --------------------------------------------------------------------------------------------------------------------
class PanelHeader(QAbstractButton):
    """Titre d'un panneau : petit losange orange, texte, et (si le panneau se replie) une flèche qui pivote."""

    def __init__(self, text: str, collapsible: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._collapsible = collapsible
        self.setCheckable(collapsible)
        self.setChecked(collapsible)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if collapsible else Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor if collapsible else Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)
        self._hover = False
        theme.bus.changed.connect(self.updateGeometry)

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        fm = QFontMetrics(make_font(font_family(), t, 15, 600))
        return QSize(fm.horizontalAdvance(self.text()) + t.px(30) + (t.px(30) if self._collapsible else 0), t.px(36))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(current().px(60), current().px(36))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        QWidget.update(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        QWidget.update(self)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = t.px(5)
        cy = self.height() / 2
        diamond = QPainterPath(QPointF(d, cy - d))
        diamond.lineTo(2 * d, cy)
        diamond.lineTo(d, cy + d)
        diamond.lineTo(0, cy)
        diamond.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("accent"))
        p.drawPath(diamond)
        p.setFont(make_font(font_family(), t, 15, 600))
        p.setPen(t.color("text"))
        right = t.px(30) if self._collapsible else 0
        text_rect = QRectF(t.px(22), 0, self.width() - t.px(22) - right, self.height())
        shown = QFontMetrics(p.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        if self._collapsible:
            icon = icons.pixmap("chevron-down" if self.isChecked() else "chevron-right",
                                t["text" if self._hover else "text-secondary"], t.px(18))
            p.drawPixmap(QPointF(self.width() - t.px(24), (self.height() - t.px(18)) / 2), icon)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), t.px(8), t.px(8))


class CollapsiblePanel(Panel):
    """Panneau avec un titre sur lequel on clique pour replier ou déplier son contenu (`body`, avec son layout `content`)."""

    toggled = Signal(bool)

    def __init__(self, title: str, accent: str = "violet", expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(accent, parent)
        outer = self.vbox(6)
        self.header = PanelHeader(title, collapsible=True)
        outer.addWidget(self.header)
        self.body = QWidget()
        self.body.setObjectName("transparent")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(10)
        outer.addWidget(self.body)
        self.header.toggled.connect(self._on_toggled)
        self.setExpanded(expanded)

    def isExpanded(self) -> bool:  # noqa: N802
        return self.header.isChecked()

    def setExpanded(self, expanded: bool) -> None:  # noqa: N802
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self.body.setVisible(expanded)
        self.header.update()

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.updateGeometry()
        self.toggled.emit(expanded)


# --------------------------------------------------------------------------------------------------------------------
#  Séparateur redimensionnable
# --------------------------------------------------------------------------------------------------------------------
class _GripHandle(QSplitterHandle):
    """Poignée du séparateur : trois points qui s'allument au survol, pour qu'on devine qu'on peut la tirer."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setToolTip("Tire pour redimensionner les panneaux")
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        QWidget.update(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        QWidget.update(self)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = t.color("accent-hover" if self._hover else "violet-text")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(color, 0.95 if self._hover else 0.55))
        horizontal = self.orientation() == Qt.Orientation.Horizontal
        r = max(1.4, t.px(1.6))
        for k in (-1, 0, 1):
            dx, dy = (0, k * t.px(9)) if horizontal else (k * t.px(9), 0)
            p.drawEllipse(QPointF(self.width() / 2 + dx, self.height() / 2 + dy), r, r)


class GripSplitter(QSplitter):
    """QSplitter dont les poignées sont visibles (voir _GripHandle)."""

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return _GripHandle(self.orientation(), self)
