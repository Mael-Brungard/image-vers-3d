"""
widgets.py - composants de l'interface de « ThreeRex » (voir docs/DESIGN.md).

Chaque composant a tous ses états : repos, survol, appui, focus clavier, désactivé. Le focus n'apparaît qu'au clavier
(politique de focus « Tab » : un clic de souris ne laisse pas d'anneau). Les couleurs viennent de theme.current() ;
les animations passent par theme.Motion et s'éteignent si Windows ou l'option « Réduire les animations » le demande.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import fx, icons, theme
from .theme import Motion, current, ease_out, font_family, make_font


# --------------------------------------------------------------------------------------------------------------------
#  Utilitaires
# --------------------------------------------------------------------------------------------------------------------
def repolish(widget: QWidget) -> None:
    """Réapplique la feuille de style après un changement de propriété dynamique."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    QWidget.update(widget)  # sur la classe de base : voir theme.repaint_later


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


def qimage_to_pil(qimage: QImage) -> Image.Image:
    qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer(
        "RGBA", (qimage.width(), qimage.height()), bytes(qimage.constBits()), "raw", "RGBA", qimage.bytesPerLine(), 1
    ).copy()


def make_button(
    text: str,
    kind: str | None = None,
    icon: str | None = None,
    large: bool = False,
    name: str | None = None,
    icon_role: str | None = None,
) -> QPushButton:
    """Bouton standard. kind : None (secondaire), « primary » (une seule action principale par vue) ou « ghost »."""
    button = QPushButton(text)
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        button.setProperty("kind", kind)
    if large:
        button.setProperty("btnsize", "lg")
    if name:
        button.setObjectName(name)
    if icon:
        role = icon_role or ("on-accent" if kind == "primary" else "text")
        icons.bind_icon(button, icon, role)
    return button


def set_kind(button: QPushButton, kind: str | None) -> None:
    """Change le rôle d'un bouton (primary / ghost / secondaire) et sa couleur d'icône."""
    if (button.property("kind") or "") == (kind or ""):
        return
    button.setProperty("kind", kind or "")
    icons.set_role(button, "on-accent" if kind == "primary" else ("text-secondary" if kind == "ghost" else "text"))
    repolish(button)


def text_label(text: str = "", role: str | None = None, name: str | None = None, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def stop_anim(anim: QVariantAnimation | None) -> None:
    """Arrête une animation, même si Qt l'a déjà détruite à la fin de son cours."""
    if anim is None:
        return
    try:
        anim.stop()
    except RuntimeError:  # objet C++ déjà supprimé
        pass


def animate(start: float, end: float, ms: int, on_value: Callable[[float], None],
            on_finished: Callable[[], None] | None = None, parent: Any = None) -> QVariantAnimation | None:
    """Anime un nombre de start à end ; sans animation (mouvement réduit), saute directement à la fin."""
    duration = Motion.ms(ms)
    if duration <= 0:
        on_value(end)
        if on_finished:
            on_finished()
        return None
    anim = QVariantAnimation(parent)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(duration)
    anim.setEasingCurve(ease_out())
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    if on_finished:
        anim.finished.connect(on_finished)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


# --------------------------------------------------------------------------------------------------------------------
#  Interrupteur
# --------------------------------------------------------------------------------------------------------------------
class Switch(QAbstractButton):
    """Interrupteur avec son libellé ; toute la ligne (44 px de haut) est cliquable."""

    TRACK_W, TRACK_H, GAP = 44, 24, 12

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)
        self._t = 0.0  # 0 = éteint, 1 = allumé
        self._anim: QVariantAnimation | None = None
        self.toggled.connect(self._on_toggled)
        theme.bus.changed.connect(self.updateGeometry)

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + t.px(self.GAP) + t.px(self.TRACK_W), t.px(44))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def _on_toggled(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not self.isVisible():
            self._t = target
            self.update()
            return
        stop_anim(self._anim)

        def step(value: float) -> None:
            self._t = value
            self.update()

        self._anim = animate(self._t, target, 150, step, parent=self)

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        if not self.isVisible():
            self._t = 1.0 if checked else 0.0

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        tw, th = t.px(self.TRACK_W), t.px(self.TRACK_H)
        track = QRectF(self.width() - tw - 2, (self.height() - th) / 2, tw, th)

        # libellé
        p.setPen(t.color("text" if enabled else "text-disabled"))
        label = QRectF(0, 0, track.left() - t.px(self.GAP), self.height())
        text = QFontMetrics(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(label.width()))
        p.setFont(self.font())
        p.drawText(label, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        # piste : contour 2 px (>= 3:1 sur le panneau) quand éteint, remplissage ambre quand allumé
        k = self._t
        off_fill, on_fill = t.color("bg-raised"), t.color("accent-ui")
        outline = t.color("border-strong" if enabled else "border")
        fill = QColor(
            round(off_fill.red() + (on_fill.red() - off_fill.red()) * k),
            round(off_fill.green() + (on_fill.green() - off_fill.green()) * k),
            round(off_fill.blue() + (on_fill.blue() - off_fill.blue()) * k),
        )
        if not enabled:
            fill = t.color("bg-raised")
        if k > 0.5 and enabled:
            outline = t.color("accent-ui")
        p.setPen(QPen(outline, 2))
        p.setBrush(fill)
        p.drawRoundedRect(track.adjusted(1, 1, -1, -1), th / 2, th / 2)

        # pastille
        pad = t.px(5)
        d = th - 2 * pad
        x = track.left() + pad + (track.width() - 2 * pad - d) * k
        on_knob = t.color("on-accent")
        knob_color = on_knob if (k > 0.5 and enabled) else t.color("text-secondary" if enabled else "text-disabled")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob_color)
        p.drawEllipse(QRectF(x, track.top() + pad, d, d))

        # focus clavier
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), t.px(8), t.px(8))


# --------------------------------------------------------------------------------------------------------------------
#  Contrôle segmenté
# --------------------------------------------------------------------------------------------------------------------
class Segmented(QWidget):
    """Choix exclusif entre 2 à 4 options courtes. Interface proche de QComboBox (addItem, currentIndex...)."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None, accessible_name: str = "") -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._index = -1
        self._hover = -1
        self._pressed = -1
        self._pos = 0.0  # position (fractionnaire) du segment actif, pour l'animation
        self._anim: QVariantAnimation | None = None
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if accessible_name:
            self.setAccessibleName(accessible_name)
        theme.bus.changed.connect(self.updateGeometry)

    # -- interface de type QComboBox --
    def addItem(self, text: str, data: Any = None, label: str | None = None, tooltip: str | None = None) -> None:  # noqa: N802
        """`text` : nom complet (accessibilité, itemText) ; `label` : texte court affiché dans le segment."""
        self._items.append({"text": text, "data": data, "label": label or text, "tip": tooltip, "enabled": True})
        if self._index < 0:
            self._index = 0
        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        self._items.clear()
        self._index = -1
        self._hover = self._pressed = -1
        self._pos = 0.0
        self.updateGeometry()
        self.update()

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:  # noqa: N802
        return self._index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._items) or index == self._index:
            return
        old = self._index
        self._index = index
        stop_anim(self._anim)
        if old < 0 or not self.isVisible():
            self._pos = float(index)
            self.update()
        else:
            def step(value: float) -> None:
                self._pos = value
                self.update()

            self._anim = animate(self._pos, float(index), 200, step, parent=self)
        self.currentIndexChanged.emit(index)

    def itemText(self, index: int) -> str:  # noqa: N802
        return self._items[index]["text"]

    def itemData(self, index: int) -> Any:  # noqa: N802
        return self._items[index]["data"]

    def currentText(self) -> str:  # noqa: N802
        return self._items[self._index]["text"] if self._index >= 0 else ""

    def currentData(self) -> Any:  # noqa: N802
        return self._items[self._index]["data"] if self._index >= 0 else None

    def setItemEnabled(self, index: int, enabled: bool, tooltip: str | None = None) -> None:  # noqa: N802
        self._items[index]["enabled"] = enabled
        if tooltip is not None:
            self._items[index]["tip"] = tooltip
        self.update()

    def isItemEnabled(self, index: int) -> bool:  # noqa: N802
        return bool(self._items[index]["enabled"])

    def blockedIndex(self, index: int) -> bool:  # noqa: N802
        return not self.isItemEnabled(index)

    # -- géométrie --
    def _font(self):
        return make_font(font_family(), current(), 14, 500)

    def _widest(self) -> int:
        fm = QFontMetrics(make_font(font_family(), current(), 14, 600))
        return max((fm.horizontalAdvance(i["label"]) for i in self._items), default=current().px(40))

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        return QSize(max(len(self._items), 1) * (self._widest() + 2 * t.px(14)), t.px(44))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        t = current()
        return QSize(max(len(self._items), 1) * (self._widest() + 2 * t.px(6)), t.px(44))  # marge du texte = celle du dessin

    def _segment_rect(self, index: float) -> QRectF:
        n = max(len(self._items), 1)
        w = self.width() / n
        return QRectF(index * w, 0, w, self.height())

    def _index_at(self, pos: QPoint) -> int:
        if not self._items:
            return -1
        i = int(pos.x() / max(self.width() / len(self._items), 1))
        return min(max(i, 0), len(self._items) - 1)

    # -- événements --
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        i = self._index_at(event.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.setToolTip(self._items[i]["tip"] or "" if self._items else "")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._index_at(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        i = self._index_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and i == self._pressed and self.isItemEnabled(i):
            self.setCurrentIndex(i)
        self._pressed = -1
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Down: 1}.get(event.key())
        if event.key() == Qt.Key.Key_Home:
            self._move_to(0, 1)
        elif event.key() == Qt.Key.Key_End:
            self._move_to(len(self._items) - 1, -1)
        elif step:
            self._move_to(self._index + step, step)
        else:
            super().keyPressEvent(event)

    def _move_to(self, index: int, direction: int) -> None:
        while 0 <= index < len(self._items):
            if self.isItemEnabled(index):
                self.setCurrentIndex(index)
                return
            index += direction

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.update()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        r = t.px(8)
        box = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setPen(QPen(t.color("border-strong" if enabled else "border"), 1.5))
        p.setBrush(t.color("bg-raised"))
        p.drawRoundedRect(box, r, r)

        inset = t.px(3)
        # survol / appui sur un segment inactif
        for i in range(len(self._items)):
            if i == self._index or not self.isItemEnabled(i) or not enabled:
                continue
            if i == self._pressed or i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(t.color("bg-pressed" if i == self._pressed else "bg-hover"))
                p.drawRoundedRect(self._segment_rect(i).adjusted(inset, inset, -inset, -inset), r - 2, r - 2)

        # segment actif
        if self._index >= 0:
            seg = self._segment_rect(self._pos).adjusted(inset, inset, -inset, -inset)
            p.setPen(QPen(t.color("accent-ui" if enabled else "border"), 1.5))
            p.setBrush(t.color("accent-soft" if enabled else "bg-hover"))
            p.drawRoundedRect(seg, r - 2, r - 2)

        # textes
        for i, item in enumerate(self._items):
            active = i == self._index
            p.setFont(make_font(font_family(), t, 14, 600 if active else 500))
            if not enabled or not item["enabled"]:
                color = t.color("text-disabled")
            else:
                color = t.color("text" if active else "text-secondary")
            p.setPen(color)
            rect = self._segment_rect(i).adjusted(t.px(6), 0, -t.px(6), 0)
            text = QFontMetrics(p.font()).elidedText(item["label"], Qt.TextElideMode.ElideRight, int(rect.width()))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        # focus clavier
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(t.color("focus"), 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), r, r)


# --------------------------------------------------------------------------------------------------------------------
#  Boutons icône, touches, puce matériel
# --------------------------------------------------------------------------------------------------------------------
class IconButton(QToolButton):
    """Bouton carré de 44 px avec une icône et une info-bulle (qui sert aussi de nom pour les lecteurs d'écran)."""

    def __init__(self, icon_name: str, tooltip: str, checkable: bool = False, name: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip.split("\n")[0])
        if name:
            self.setObjectName(name)
        icons.bind_icon(self, icon_name, "text", active="accent-text")


class ElidedLabel(QLabel):
    """Libellé sur une ligne, coupé par « … » à droite quand il manque de place (le texte complet reste dans l'info-bulle)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, QFontMetrics(self.font()).height() + 2)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._full) + 4, fm.height() + 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)


class KeyCap(QLabel):
    """Touche de clavier (« Ctrl », « O »...) pour les états vides qui enseignent les raccourcis."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("keycap")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName(text)


class HardwareChip(QFrame):
    """Pastille d'état du calcul : « GPU : NVIDIA ... » avec un point vert lumineux, ou « Processeur (lent) » avec un point
    ambre (avertissement). Le point n'est jamais la seule information : le texte dit la même chose."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 16, 0)
        layout.setSpacing(10)
        self._text = ElidedLabel()
        self._text.setProperty("role", "caption")
        self._text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)  # la pastille prend la largeur du texte
        self._dot = QLabel()
        layout.addWidget(self._text)
        layout.addWidget(self._dot)
        self._gpu = True
        self._full = ""
        self.set_device("")
        theme.bus.changed.connect(self._restyle)

    def set_device(self, text: str) -> None:
        self._full = text
        self._gpu = text.startswith("GPU")
        self._text.setText(text)  # ElidedLabel : se coupe seul quand la barre manque de place
        self.setToolTip(text)
        self.setAccessibleName(f"Calcul : {text}")
        self.setVisible(bool(text))
        self._restyle()

    def _restyle(self) -> None:
        t = current()
        self.setFixedHeight(t.px(38))
        size = t.px(14)
        dpr = 2.0
        pix = QPixmap(int(size * dpr), int(size * dpr))
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(dpr, dpr)
        color = t.color("success" if self._gpu else "warning")
        glow = QRadialGradient(QPointF(size / 2, size / 2), size / 2)
        glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 120))
        glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(size / 2, size / 2), size / 2, size / 2)
        p.setBrush(color)
        p.drawEllipse(QPointF(size / 2, size / 2), size * 0.26, size * 0.26)
        p.end()
        pix.setDevicePixelRatio(dpr)
        self._dot.setPixmap(pix)


# --------------------------------------------------------------------------------------------------------------------
#  Progression et illustration animée
# --------------------------------------------------------------------------------------------------------------------
class IndeterminateBar(QWidget):
    """Barre de progression sans valeur : un segment ambre qui glisse. Statique si le mouvement est réduit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._start = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        self.setFixedHeight(current().px(4))
        theme.bus.changed.connect(lambda: self.setFixedHeight(current().px(4)))

    def isActive(self) -> bool:  # noqa: N802
        return self._active

    def setActive(self, active: bool) -> None:  # noqa: N802
        if active == self._active:
            return
        self._active = active
        if active:
            self._start = time.monotonic()
            if Motion.enabled():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("bg-pressed"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        if not self._active:
            return
        seg = self.width() * 0.34
        if Motion.enabled():
            phase = ((time.monotonic() - self._start) % 1.5) / 1.5
            k = 1 - (1 - phase) ** 3  # départ rapide, arrivée douce
            x = -seg + (self.width() + seg) * k
        else:
            x = (self.width() - seg) / 2  # pas de mouvement : segment fixe, l'état reste lisible via le texte
        p.setBrush(t.color("accent-ui"))
        p.setClipRect(QRectF(0, 0, self.width(), h))
        p.drawRoundedRect(QRectF(x, 0, seg, h), h / 2, h / 2)


class HeroMark(QWidget):
    """Globe en fil de fer qui tourne lentement : repère visuel des états vides et du calcul en cours."""

    def __init__(self, size: int = 144, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = size
        self._phase = 0.0
        self._speed = 0.5  # rad/s
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(current().px(size), current().px(size))
        theme.bus.changed.connect(lambda: self.setFixedSize(current().px(self._base), current().px(self._base)))

    def set_fast(self, fast: bool) -> None:
        self._speed = 1.6 if fast else 0.5

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._last = time.monotonic()
        if Motion.enabled():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        self._phase = (self._phase + (now - self._last) * self._speed) % math.pi
        self._last = now
        if not Motion.enabled():
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        radius = min(self.width(), self.height()) / 2 - 3
        wire = t.color("text-muted", 0.55)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(wire, 1.5))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        for k in range(6):  # méridiens
            w = abs(math.cos(self._phase + k * math.pi / 6)) * radius
            p.drawEllipse(QPointF(cx, cy), w, radius)
        for lat in (-0.55, 0.55):  # parallèles
            half = radius * math.sqrt(1 - lat * lat)
            p.drawEllipse(QPointF(cx, cy + radius * lat), half, half * 0.26)
        p.setPen(QPen(t.color("accent-ui"), 2))  # équateur : le seul trait ambre
        p.drawEllipse(QPointF(cx, cy), radius, radius * 0.26)


# --------------------------------------------------------------------------------------------------------------------
#  Image : aperçu et zone de dépôt
# --------------------------------------------------------------------------------------------------------------------
class ImagePreview(QWidget):
    """Affiche une image à la bonne échelle, coins arrondis, entre quatre repères de visée. `start_scan` : une ligne
    lumineuse balaie l'image une fois (à l'import)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._scan = -1.0  # position de la ligne de balayage : 0..1, -1 = aucune
        self._scan_anim: QVariantAnimation | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:  # noqa: N802
        t = current()
        return QSize(t.px(300), t.px(190))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        t = current()
        return QSize(t.px(120), t.px(120))

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    def scanning(self) -> bool:
        return self._scan >= 0.0

    def start_scan(self) -> None:
        """Balayage de l'image importée (900 ms). Sans effet si les effets sont coupés : l'image apparaît simplement."""
        stop_anim(self._scan_anim)
        self._scan = -1.0
        if not Motion.ambient() or self._pixmap is None:
            self.update()
            return

        def step(value: float) -> None:
            self._scan = value
            self.update()

        def done() -> None:
            self._scan = -1.0
            self.update()

        self._scan_anim = animate(0.0, 1.0, 900, step, on_finished=done, parent=self)

    def image_rect(self) -> QRectF:
        t = current()
        pad = t.px(12)
        if self._pixmap is None or self._pixmap.isNull():
            return QRectF()
        avail = QSize(max(self.width() - 2 * pad, 1), max(self.height() - 2 * pad, 1))
        scaled = self._pixmap.size().scaled(avail, Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - scaled.width()) / 2, (self.height() - scaled.height()) / 2, scaled.width(), scaled.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pixmap is None or self._pixmap.isNull():
            return
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = self.image_rect()
        path = QPainterPath()
        path.addRoundedRect(target, t.px(6), t.px(6))
        p.save()
        p.setClipPath(path)
        p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        if self._scan >= 0.0:
            y = target.top() + target.height() * self._scan
            veil = QLinearGradient(QPointF(0, target.top()), QPointF(0, y))  # voile violet sur la partie déjà analysée
            veil.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.0))
            veil.setColorAt(1.0, fx.with_alpha(t.color("violet"), 0.30))
            p.fillRect(QRectF(target.left(), target.top(), target.width(), y - target.top()), QBrush(veil))
            band = QLinearGradient(QPointF(0, y - t.px(18)), QPointF(0, y))
            band.setColorAt(0.0, fx.with_alpha(t.color("accent-hover"), 0.0))
            band.setColorAt(1.0, fx.with_alpha(t.color("accent-hover"), 0.45))
            p.fillRect(QRectF(target.left(), y - t.px(18), target.width(), t.px(18)), QBrush(band))
            p.setPen(QPen(t.color("accent-hover"), 2))
            p.drawLine(QPointF(target.left(), y), QPointF(target.right(), y))
        p.restore()
        # repères de visée aux quatre coins
        arm = min(t.px(16), target.width() / 4, target.height() / 4)
        p.setPen(QPen(t.color("accent"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        r = target.adjusted(-3, -3, 3, 3)
        for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * arm, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * arm))


class HaloIcon(fx.Animated):
    """Halo de la zone d'import : un disque lumineux entouré d'orbites avec de petits satellites. Plus vif quand un fichier
    survole la zone. Immobile (même dessin, sans mouvement) si les effets sont coupés."""

    EVERY = 2

    def __init__(self, size: int = 92, icon: str = "image-up", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = size
        self._icon = icon
        self._boost = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        theme.bus.changed.connect(self._refit)
        self._refit()

    def _refit(self) -> None:
        s = current().px(self._base)
        self.setFixedSize(s, s)

    def set_boost(self, on: bool) -> None:
        self._boost = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        clock = fx.Clock.t()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        radius = min(self.width(), self.height()) / 2 - 2
        pulse = 1.0 + 0.06 * math.sin(clock * 2.0) if clock else 1.0
        tint = t.color("accent") if self._boost else t.color("violet")
        halo = QRadialGradient(QPointF(cx, cy), radius * pulse)
        halo.setColorAt(0.0, fx.with_alpha(tint, 0.42 + 0.2 * self._boost))
        halo.setColorAt(0.6, fx.with_alpha(tint, 0.14))
        halo.setColorAt(1.0, fx.with_alpha(tint, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        speed = 0.5 + 0.9 * self._boost
        rings = ((0.96, 0.36, -24.0, 1.0), (0.96, 0.36, 36.0, -0.8), (0.74, 0.74, 0.0, 0.6))
        for k, (rx, ry, tilt, direction) in enumerate(rings):
            p.save()
            p.translate(cx, cy)
            p.rotate(tilt + (clock * 6.0 * direction * speed if clock else 0.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(fx.with_alpha(t.color("violet-hover"), 0.55), 1.2))
            p.drawEllipse(QPointF(0, 0), radius * rx, radius * ry)
            sat = (clock * speed * direction * 1.3 if clock else 0.9) + k * 2.1
            sx, sy = math.cos(sat) * radius * rx, math.sin(sat) * radius * ry
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fx.with_alpha(t.color("accent-hover"), 0.28))
            p.drawEllipse(QPointF(sx, sy), 5.0, 5.0)
            p.setBrush(t.color("accent-hover"))
            p.drawEllipse(QPointF(sx, sy), 2.2, 2.2)
            p.restore()
        disc = radius * 0.5
        fill = QRadialGradient(QPointF(cx - disc * 0.3, cy - disc * 0.3), disc * 1.4)
        fill.setColorAt(0.0, t.color("violet-soft"))
        fill.setColorAt(1.0, t.color("bg-deep"))
        p.setBrush(QBrush(fill))
        p.setPen(QPen(t.color("violet-hover"), 1.4))
        p.drawEllipse(QPointF(cx, cy), disc, disc)
        icon_size = max(int(disc * 1.0), 12)
        pix = icons.pixmap(self._icon, t["text"], icon_size)
        p.drawPixmap(QPointF(cx - icon_size / 2, cy - icon_size / 2), pix)


class DropZone(QWidget):
    """Zone d'import : vide (halo animé qui enseigne les gestes), survolée par un fichier, ou chargée (image entre repères,
    bascule Originale / Détourée et bouton Changer)."""

    openRequested = Signal()
    pasteRequested = Signal()
    viewChanged = Signal(int)  # 0 = originale, 1 = détourée

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAccessibleName("Zone de dépôt d'image")
        self._dragging = False
        self._original: QPixmap | None = None
        self._prepared: QPixmap | None = None
        self._has_image = False

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        # --- page vide
        empty = QWidget()
        empty.setObjectName("transparent")
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(16, 16, 16, 16)
        ev.setSpacing(6)
        ev.addStretch(1)
        self.halo = HaloIcon(88)
        ev.addWidget(self.halo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = text_label("Dépose ton image ici", name="h2")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        ev.addWidget(self.title)
        self.hint = text_label("PNG, JPG ou WebP. Un objet bien visible sur un fond simple donne le meilleur résultat.",
                               role="muted", wrap=True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self.hint)
        buttons = QWidget()
        buttons.setObjectName("transparent")
        flow = fx.FlowLayout(buttons, 8, 4, centered=True)
        self.btn_open = fx.GlowButton("Choisir une image", kind=None, tall=False, icon_after=False)
        self.btn_open.setObjectName("btn_open")
        icons.bind_icon(self.btn_open, "image-up", "text")
        self.btn_open.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_paste = make_button("Coller", kind="ghost", icon="clipboard-paste", name="btn_paste", icon_role="text-secondary")
        self.btn_open.clicked.connect(self.openRequested)
        self.btn_paste.clicked.connect(self.pasteRequested)
        flow.addWidget(self.btn_open)
        flow.addWidget(self.btn_paste)
        self._buttons = buttons
        ev.addWidget(buttons)
        ev.addStretch(1)
        self._stack.addWidget(empty)

        # --- page chargée
        loaded = QWidget()
        loaded.setObjectName("transparent")
        lv = QVBoxLayout(loaded)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(8)
        self.image = ImagePreview()
        lv.addWidget(self.image, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.view = Segmented(accessible_name="Image affichée")
        self.view.addItem("Originale")
        self.view.addItem("Détourée", tooltip="Voir l'image telle que le modèle 3D la reçoit")
        self.view.currentIndexChanged.connect(self._on_view)
        self.btn_change = make_button("Changer", kind="ghost", icon="image-up", name="btn_change", icon_role="text-secondary")
        self.btn_change.clicked.connect(self.openRequested)
        row.addWidget(self.view, 1)
        row.addWidget(self.btn_change)
        lv.addLayout(row)
        self._stack.addWidget(loaded)

        self.setMinimumHeight(current().px(236))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        theme.bus.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        self.setMinimumHeight(current().px(236))
        self.update()

    # -- état --
    def has_image(self) -> bool:
        return self._has_image

    def set_image(self, image: Image.Image | None) -> None:
        self._original = pil_to_pixmap(image) if image is not None else None
        self._prepared = None
        self._has_image = image is not None
        self._stack.setCurrentIndex(1 if self._has_image else 0)
        self.view.blockSignals(True)
        self.view.setCurrentIndex(0)
        self.view.blockSignals(False)
        self._show_current()
        if self._has_image:
            self.image.start_scan()
        self.update()

    def set_prepared(self, image: Image.Image | None, select: bool = True) -> None:
        """Image telle que le modèle la reçoit (détourée). `select` : bascule l'affichage dessus."""
        self._prepared = pil_to_pixmap(image) if image is not None else None
        if self._prepared is None:
            self.view.blockSignals(True)
            self.view.setCurrentIndex(0)
            self.view.blockSignals(False)
        elif select:
            self.view.blockSignals(True)
            self.view.setCurrentIndex(1)
            self.view.blockSignals(False)
        self._show_current()

    def has_prepared(self) -> bool:
        return self._prepared is not None

    def shows_prepared(self) -> bool:
        return self.view.currentIndex() == 1 and self._prepared is not None

    def pixmap(self) -> QPixmap | None:
        return self.image.pixmap()

    def _show_current(self) -> None:
        use_prepared = self.view.currentIndex() == 1 and self._prepared is not None
        self.image.set_pixmap(self._prepared if use_prepared else self._original)

    def _on_view(self, index: int) -> None:
        self._show_current()
        self.viewChanged.emit(index)

    def set_dragging(self, dragging: bool) -> None:
        if dragging != self._dragging:
            self._dragging = dragging
            self.title.setText("Relâche pour charger l'image" if dragging else "Dépose ton image ici")
            self.halo.set_boost(dragging)
            self.update()

    def setControlsEnabled(self, enabled: bool) -> None:  # noqa: N802
        for w in (self.btn_open, self.btn_paste, self.btn_change, self.view):
            w.setEnabled(enabled)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._has_image and event.button() == Qt.MouseButton.LeftButton and self.btn_open.isEnabled():
            self.openRequested.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = fx.chamfer_path(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), tl=t.px(12), br=t.px(12))
        if self._dragging:
            fx.glow_stroke(p, path, t.color("accent"), 3.0, 1.0)
            p.setPen(QPen(t.color("accent-ui"), 2))
            p.setBrush(fx.with_alpha(t.color("accent-soft"), 0.85))
        elif self._has_image:
            p.setPen(QPen(fx.with_alpha(t.color("violet"), 0.8), 1.2))
            p.setBrush(fx.with_alpha(t.color("bg-viewport"), 0.9))
        else:
            fill = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
            fill.setColorAt(0.0, fx.with_alpha(t.color("violet-soft"), 0.55))
            fill.setColorAt(1.0, fx.with_alpha(t.color("bg-viewport"), 0.8))
            pen = QPen(t.color("violet-hover"), 1.6)
            pen.setDashPattern([4.0, 4.0])
            p.setPen(pen)
            p.setBrush(QBrush(fill))
        p.drawPath(path)


# --------------------------------------------------------------------------------------------------------------------
#  Notification (toast) et panneau d'erreur
# --------------------------------------------------------------------------------------------------------------------
class Toast(QFrame):
    """Message bref, non modal, en bas du visualiseur. Disparaît seul (5 s, suspendu au survol) ou avec Échap."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 6, 6)
        layout.setSpacing(12)
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._close = IconButton("x", "Fermer la notification")
        self._close.clicked.connect(self.dismiss)
        layout.addWidget(self._icon)
        layout.addWidget(self._text, 1)
        layout.addWidget(self._close)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._kind = "success"
        self._reserved = 0
        self._anim: QVariantAnimation | None = None
        self.hide()

    def show_message(self, text: str, kind: str = "success", timeout: int = 5000) -> None:
        t = current()
        self._kind = kind
        name, role = {"success": ("circle-check", "success"), "error": ("circle-alert", "danger"),
                      "warning": ("triangle-alert", "warning")}.get(kind, ("info", "info"))
        self._icon.setPixmap(icons.pixmap(name, t[role], 20))
        self._text.setText(text)
        self.setAccessibleName(text)
        self._timer.stop()
        fm = QFontMetrics(self._text.font())
        text_w = min(fm.horizontalAdvance(text) + 6, t.px(460))
        self._text.setFixedWidth(text_w)
        self.layout().activate()
        self.adjustSize()
        self.show()
        self.raise_()
        self.reposition(self._reserved)
        stop_anim(self._anim)
        base_y = self.y()

        def step(value: float) -> None:
            self._effect.setOpacity(value)
            self.move(self.x(), round(base_y + (1 - value) * 8))

        self._anim = animate(0.0, 1.0, 200, step, parent=self)
        if timeout > 0:
            self._timer.start(timeout)

    def reposition(self, reserved_bottom: int = 0) -> None:
        """Bas du visualiseur, centré ; `reserved_bottom` laisse la place aux éléments déjà posés en bas."""
        parent = self.parentWidget()
        if parent is None:
            return
        self._reserved = reserved_bottom
        self.adjustSize()
        margin = current().px(24)
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - margin - reserved_bottom)

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        self._timer.stop()
        stop_anim(self._anim)
        self._anim = animate(1.0, 0.0, 150, self._effect.setOpacity, on_finished=self.hide, parent=self)

    def hide_now(self) -> None:
        """Retire la notification tout de suite (changement d'état de l'application)."""
        self._timer.stop()
        stop_anim(self._anim)
        self._effect.setOpacity(1.0)
        self.hide()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.isVisible():
            self._timer.start(2500)
        super().leaveEvent(event)

    def message(self) -> str:
        return self._text.text()

    def kind(self) -> str:
        return self._kind


class ErrorPanel(QFrame):
    """Erreur en ligne (jamais une fenêtre modale) : dit ce qui s'est passé, quoi faire, et offre les actions."""

    retry = Signal()
    copyDetails = Signal()
    openLog = Signal()
    back = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("errorPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 32, 32, 28)
        v.setSpacing(12)
        self._icon = QLabel()
        v.addWidget(self._icon)
        self.title = text_label("", name="title", wrap=True)
        self.message = text_label("", role="secondary", wrap=True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hint = text_label("", role="muted", wrap=True)
        v.addWidget(self.title)
        v.addWidget(self.message)
        v.addWidget(self.hint)
        v.addSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_retry = make_button("Réessayer", kind="primary", icon="refresh-cw", name="btn_retry")
        self.btn_copy = make_button("Copier les détails", icon="copy", name="btn_copy_details")
        self.btn_log = make_button("Ouvrir le journal", kind="ghost", icon="file-text", name="btn_open_log",
                                   icon_role="text-secondary")
        self.btn_back = make_button("Revenir au modèle", kind="ghost", icon="box", name="btn_back_to_model",
                                    icon_role="text-secondary")
        self.btn_retry.clicked.connect(self.retry)
        self.btn_copy.clicked.connect(self.copyDetails)
        self.btn_log.clicked.connect(self.openLog)
        self.btn_back.clicked.connect(self.back)
        actions.addWidget(self.btn_retry)
        actions.addWidget(self.btn_copy)
        actions.addStretch(1)
        v.addLayout(actions)
        second = QHBoxLayout()
        second.setSpacing(8)
        second.addWidget(self.btn_log)
        second.addWidget(self.btn_back)
        second.addStretch(1)
        v.addLayout(second)
        self.details = ""
        self.setFixedWidth(current().px(520))  # largeur définie : les textes longs se replient correctement
        theme.bus.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        self.setFixedWidth(current().px(520))
        self._icon.setPixmap(icons.pixmap("triangle-alert", current()["danger"], 32))
        self._fit_height()

    def _fit_height(self) -> None:
        """Hauteur exacte pour la largeur fixe : un layout parent qui centre le panneau ignorerait la hauteur des textes
        qui passent à la ligne (ils seraient coupés ou les boutons se chevaucheraient)."""
        layout = self.layout()
        layout.activate()
        self.setFixedHeight(layout.totalHeightForWidth(self.width()))

    def set_error(self, title: str, message: str, hint: str, details: str, can_go_back: bool, retry_label: str) -> None:
        self.title.setText(title)
        self.message.setText(message)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.details = details
        self.btn_back.setVisible(can_go_back)
        self.btn_retry.setText(retry_label)
        self.btn_copy.setVisible(bool(details))
        self.setAccessibleName(f"{title}. {message}")
        self._fit_height()


# --------------------------------------------------------------------------------------------------------------------
#  Pages du visualiseur : vide et calcul en cours
# --------------------------------------------------------------------------------------------------------------------
class MascotHero(fx.Animated):
    """La mascotte, grande, qui flotte doucement au-dessus d'une ombre lumineuse (immobile si les effets sont coupés)."""

    EVERY = 2

    def __init__(self, size: int = 168, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = size
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Mascotte ThreeRex")
        theme.bus.changed.connect(self._refit)
        self._refit()

    def _refit(self) -> None:
        s = current().px(self._base)
        self.setFixedSize(s, int(s * 1.08))

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        clock = fx.Clock.t()
        bob = math.sin(clock * 1.6) * self.height() * 0.018 if clock else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height() / 1.08)
        shadow_w = size * (0.62 - 0.04 * math.sin(clock * 1.6)) if clock else size * 0.62
        base = QRadialGradient(QPointF(self.width() / 2, self.height() - size * 0.05), shadow_w / 2)
        base.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.45))
        base.setColorAt(1.0, fx.with_alpha(t.color("violet"), 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(base))
        p.drawEllipse(QPointF(self.width() / 2, self.height() - size * 0.05), shadow_w / 2, shadow_w * 0.09)
        fx.paint_mark(p, QRectF((self.width() - size) / 2, size * 0.02 + bob, size, size), glow=1.0)


class EmptyState(QWidget):
    """Page du visualiseur avant le premier modèle : mascotte, ce qu'il faut faire, raccourcis."""

    SHORTCUTS = (
        (("Ctrl", "O"), "Ouvrir une image"),
        (("Ctrl", "V"), "Coller une image"),
        (("Ctrl", "Entrée"), "Lancer la génération"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparent")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(8)
        v.addStretch(1)
        self.mark = MascotHero(168)
        v.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(12)
        self.title = text_label("Ton modèle 3D apparaîtra ici", name="title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.sub = text_label("Dépose une image à gauche, puis lance la génération. Tout reste sur ton ordinateur.",
                              role="secondary", wrap=True)
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.sub)
        v.addSpacing(12)
        self.shortcuts = QWidget()
        self.shortcuts.setObjectName("transparent")
        rows = QVBoxLayout(self.shortcuts)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        for keys, label in self.SHORTCUTS:
            row = QHBoxLayout()
            row.setSpacing(6)
            holder = QWidget()
            holder.setObjectName("transparent")
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            hl.addStretch(1)
            for k in keys:
                hl.addWidget(KeyCap(k))
            holder.setMinimumWidth(150)
            row.addWidget(holder)
            row.addSpacing(8)
            row.addWidget(text_label(label, role="caption"), 1)
            rows.addLayout(row)
        v.addWidget(self.shortcuts, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(2)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Dans un visualiseur bas, la mascotte et les raccourcis s'effacent avant que le texte ne soit coupé."""
        super().resizeEvent(event)
        tall = self.height() >= current().px(520)
        self.shortcuts.setVisible(tall)
        self.mark.setVisible(self.height() >= current().px(380))


class BusyState(QWidget):
    """Page du visualiseur pendant le calcul : reconstruction animée de l'image (ou globe s'il n'y en a pas encore),
    titre de l'étape et message courant. Aucune durée ni pourcentage inventés : on ne les connaît pas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparent")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(8)
        self.recon = fx.ReconstructionView()
        v.addWidget(self.recon, 1)
        self.mark = HeroMark(120)
        self.mark.set_fast(True)
        v.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = text_label("Génération en cours", name="title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.status = text_label("", role="secondary", wrap=True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setMaximumWidth(current().px(520))
        # centré par deux ressorts (et non par un alignement de layout, qui ignore la hauteur d'un texte qui passe à la ligne)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.status, 100)
        row.addStretch(1)
        v.addLayout(row)
        self.note = text_label("Le calcul se fait sur ta machine : tu peux laisser la fenêtre ouverte.", role="muted",
                               wrap=True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.note)
        self._show_source(False)
        theme.bus.changed.connect(lambda: self.status.setMaximumWidth(current().px(520)))

    def _show_source(self, has_source: bool) -> None:
        self.recon.setVisible(has_source)
        self.mark.setVisible(not has_source)

    def set_source(self, image: Image.Image | None) -> None:
        """Image que le modèle reçoit : la reconstruction en tire ses points. None : retour au globe."""
        self.recon.set_source(image)
        self._show_source(image is not None)

    def set_status(self, text: str) -> None:
        self.status.setText(text)


def animate_property(target: QWidget, prop: bytes, start: Any, end: Any, ms: int) -> QPropertyAnimation | None:
    """Anime une propriété Qt avec la courbe commune ; None si le mouvement est réduit (la valeur est posée)."""
    duration = Motion.ms(ms)
    if duration <= 0:
        target.setProperty(prop.decode(), end)
        return None
    anim = QPropertyAnimation(target, prop, target)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setDuration(duration)
    anim.setEasingCurve(ease_out())
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim
