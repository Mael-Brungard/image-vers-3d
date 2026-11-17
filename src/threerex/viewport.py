"""
viewport.py - zone centrale de ThreeRex : visualiseur 3D, pages (vide, calcul, résultat, erreur) et commandes flottantes.

Le visualiseur 3D (pyqtgraph/OpenGL) se commande à la souris : clic gauche = geste du mode choisi (pivoter, déplacer ou zoomer),
molette = zoom, clic milieu = déplacer, clic droit = zoom. Les effets visuels (particules, transition) se mettent en pause
pendant un geste et ne touchent jamais à la scène 3D elle-même.
"""

from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen, QPixmap, QPolygon, QRadialGradient, QRegion
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from . import fx, icons, theme
from .geometry import ORIENTATION, display_arrays
from .theme import Motion, current
from .widgets import BusyState, EmptyState, ErrorPanel, IconButton, Segmented, Toast, animate, stop_anim

log = logging.getLogger("studio")

MODES = ("rotate", "pan", "zoom")


def drag_action(mode: str, buttons, modifiers=Qt.KeyboardModifier.NoModifier) -> str | None:
    """Ce que fait un glisser de souris dans le visualiseur : « orbit », « pan », « zoom » ou rien.
    Clic gauche : geste du mode choisi (Ctrl = déplacer) ; clic milieu : déplacer ; clic droit : zoom."""
    left = bool(buttons & Qt.MouseButton.LeftButton)
    middle = bool(buttons & Qt.MouseButton.MiddleButton)
    right = bool(buttons & Qt.MouseButton.RightButton)
    if left and not middle and not right:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            return "pan"
        return {"rotate": "orbit", "pan": "pan", "zoom": "zoom"}.get(mode, "orbit")
    if middle and not left and not right:
        return "pan"
    if right and not left and not middle:
        return "zoom"
    return None


class MeshViewer(QStackedWidget):
    """Visionneuse 3D (pyqtgraph/OpenGL)."""

    CAMERA = dict(distance=3.4, elevation=18, azimuth=-90)
    SPIN_DEGREES = 0.45  # par image (~27°/s)
    EDGE_COLOR = {"dark": (0.05, 0.04, 0.12, 1.0)}
    interacted = Signal()  # un geste de souris commence ou continue : les effets d'ambiance se mettent en pause

    def __init__(self) -> None:
        super().__init__()
        self._placeholder = QLabel("")
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setObjectName("viewerPlaceholder")
        self.addWidget(self._placeholder)

        self._view = None
        self._grid = None
        self._item = None
        self._wireframe = False
        self.mode = "rotate"
        self._last: tuple | None = None  # (maillage, orientation) pour redessiner quand le thème change
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._spin_step)

    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self.mode = mode

    def _ensure_view(self) -> bool:
        if self._view is not None:
            return True
        try:
            import pyqtgraph.opengl as gl

            self._gl = gl
            viewer = self

            class InteractiveView(gl.GLViewWidget):
                """GLViewWidget dont le clic gauche suit le mode choisi (pivoter, déplacer, zoomer)."""

                def mousePressEvent(self, ev):  # noqa: N802
                    viewer.interacted.emit()
                    super().mousePressEvent(ev)

                def mouseMoveEvent(self, ev):  # noqa: N802
                    pos = ev.position()
                    if not hasattr(self, "mousePos"):
                        self.mousePos = pos
                    diff = pos - self.mousePos
                    self.mousePos = pos
                    action = drag_action(viewer.mode, ev.buttons(), ev.modifiers())
                    if action is None:
                        return
                    viewer.interacted.emit()
                    if action == "orbit":
                        self.orbit(-diff.x(), diff.y())
                    elif action == "pan":
                        self.pan(diff.x(), diff.y(), 0, relative="view-upright")
                    else:
                        self.opts["distance"] = min(max(self.opts["distance"] * 1.012 ** diff.y(), 0.4), 40.0)
                        self.update()

                def wheelEvent(self, ev):  # noqa: N802
                    viewer.interacted.emit()
                    super().wheelEvent(ev)

            self._view = InteractiveView()
            self._view.setCameraPosition(**self.CAMERA)
            self._grid = gl.GLGridItem()
            self._grid.setSize(3, 3)
            self._grid.setSpacing(0.25, 0.25)
            self._view.addItem(self._grid)
            self.addWidget(self._view)
            self.apply_theme()
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Visionneuse 3D indisponible :\n%s", traceback.format_exc())
            self._placeholder.setText(
                "La visionneuse 3D n'a pas pu démarrer (%s).\n\n"
                "Tu peux quand même enregistrer le modèle et l'ouvrir dans Blender." % exc
            )
            return False

    def apply_theme(self) -> None:
        """Fond et grille suivent le thème ; le modèle est redessiné avec la couleur de matière du thème."""
        t = theme.current()
        if self._view is not None:
            try:
                self._view.setBackgroundColor(t.color("bg-viewport"))
                if self._grid is not None:
                    self._grid.setColor(t.color("violet", 0.42))
            except Exception:  # noqa: BLE001 - un échec de style ne doit jamais empêcher l'affichage
                log.warning("Couleurs de la visionneuse non appliquées :\n%s", traceback.format_exc())
        if self._last is not None:
            self.set_mesh(*self._last)

    def set_mesh(self, mesh, orientation=ORIENTATION) -> None:
        if not self._ensure_view():
            return
        self._last = (mesh, orientation)
        gl = self._gl
        mode = theme.current().mode
        vertices, faces, colors, z_min = display_arrays(mesh, orientation=orientation)
        if colors is not None:
            data = gl.MeshData(vertexes=vertices, faces=faces, vertexColors=colors)
        else:
            data = gl.MeshData(vertexes=vertices, faces=faces)
        if self._item is not None:
            self._view.removeItem(self._item)
        self._item = gl.GLMeshItem(
            meshdata=data,
            smooth=True,
            shader="shaded",
            color=theme.MESH_COLOR[mode],
            drawEdges=self._wireframe,
            edgeColor=self.EDGE_COLOR[mode],
        )
        self._view.addItem(self._item)
        self._grid.resetTransform()
        self._grid.translate(0, 0, z_min)
        self.setCurrentWidget(self._view)

    def clear(self) -> None:
        """Retire le modèle affiché (nouvelle image : l'ancien résultat n'est plus d'actualité)."""
        self._last = None
        self.set_auto_rotate(False)
        if self._view is not None and self._item is not None:
            self._view.removeItem(self._item)
            self._item = None

    def reset_view(self) -> None:
        if self._view is not None:
            self._view.setCameraPosition(**self.CAMERA)
            try:
                self._view.opts["center"] = type(self._view.opts["center"])(0, 0, 0)
            except Exception:  # noqa: BLE001 - la caméra revient au moins à sa distance et ses angles
                pass
            self._view.update()

    def set_wireframe(self, enabled: bool) -> None:
        self._wireframe = enabled
        if self._item is not None:
            self._item.opts["drawEdges"] = enabled
            self._item.update()

    def set_auto_rotate(self, enabled: bool) -> None:
        if enabled and self._view is not None:
            self._spin.start()
        else:
            self._spin.stop()

    def _spin_step(self) -> None:
        try:
            self._view.orbit(self.SPIN_DEGREES, 0)
        except Exception:  # noqa: BLE001
            self._spin.stop()


class RevealOverlay(QWidget):
    """Transition image -> modèle : l'image envoyée au moteur est balayée de gauche à droite par une ligne lumineuse et
    se dissout, laissant apparaître le modèle 3D dessous. 900 ms, une seule fois, jamais si les effets sont coupés."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._pixmap: QPixmap | None = None
        self._progress = 0.0
        self._anim = None
        self.hide()

    def running(self) -> bool:
        return self.isVisible()

    def start(self, pixmap: QPixmap | None) -> bool:
        """Lance la transition ; renvoie False (rien ne se passe) si elle est coupée ou s'il n'y a pas d'image."""
        self.stop()
        if pixmap is None or pixmap.isNull() or not Motion.ambient():
            return False
        self._pixmap = pixmap
        self._progress = 0.0
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()

        def step(value: float) -> None:
            self._progress = value
            self.update()

        self._anim = animate(0.0, 1.0, 900, step, on_finished=self.stop, parent=self)
        return True

    def stop(self) -> None:
        stop_anim(self._anim)
        self._anim = None
        self._progress = 0.0
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pixmap is None:
            return
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        avail = self.rect().adjusted(t.px(40), t.px(40), -t.px(40), -t.px(40))
        size = self._pixmap.size().scaled(avail.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(avail.center().x() - size.width() / 2, avail.center().y() - size.height() / 2, size.width(), size.height())
        x = target.left() + target.width() * self._progress
        p.save()
        p.setClipRect(QRectF(x, target.top(), target.right() - x + 1, target.height()))  # la part pas encore balayée
        p.setOpacity(0.92)
        p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        p.restore()
        glow = QLinearGradient(QPointF(x - t.px(26), 0), QPointF(x, 0))
        glow.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.0))
        glow.setColorAt(1.0, fx.with_alpha(t.color("accent-hover"), 0.5))
        p.fillRect(QRectF(x - t.px(26), target.top() - 8, t.px(26), target.height() + 16), QBrush(glow))
        p.setPen(QPen(t.color("accent-hover"), 2))
        p.drawLine(QPointF(x, target.top() - 8), QPointF(x, target.bottom() + 8))


class ViewportFrame(QFrame):
    """Zone centrale : une page à la fois (vide, calcul, résultat, erreur) dans un cadre lumineux et, par-dessus, les commandes
    flottantes : haut gauche la pastille d'information, haut droite les outils, bas au centre les gestes (pivoter, déplacer,
    zoomer, réinitialiser), bas à droite le choix de variante."""

    EMPTY, BUSY, RESULT, ERROR = "empty", "busy", "result", "error"
    fullscreenRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("viewport")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setMinimumSize(320, 300)

        self.stack = QStackedWidget(self)
        self.empty = EmptyState()
        self.busy = BusyState()
        self.viewer = MeshViewer()
        self.error = ErrorPanel()
        error_page = QWidget()
        error_page.setObjectName("transparent")
        ev = QVBoxLayout(error_page)
        ev.setContentsMargins(24, 24, 24, 24)
        ev.addStretch(1)
        ev.addWidget(self.error, 0, Qt.AlignmentFlag.AlignHCenter)
        ev.addStretch(1)
        self._pages = {self.EMPTY: self.empty, self.BUSY: self.busy, self.RESULT: self.viewer, self.ERROR: error_page}
        for page in self._pages.values():
            self.stack.addWidget(page)

        self.particles = fx.ParticleField("drift", self)
        self.reveal = RevealOverlay(self)

        # outils d'affichage (haut droite)
        self.info = QLabel("", self)
        self.info.setObjectName("infoPill")
        self._info_full = ""
        self.help = QLabel("", self)
        self.help.setObjectName("infoPill")
        self.help.setWordWrap(True)
        self.help.setText("Clic gauche : geste du mode choisi · Molette : zoom · Clic milieu : déplacer · Clic droit : zoom")
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("floatBar")
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(4, 4, 4, 4)
        tb.setSpacing(2)
        self.btn_spin = IconButton("orbit", "Faire tourner automatiquement", checkable=True, name="btn_spin")
        self.btn_turn = IconButton("rotate-cw", "Pivoter de 90°\nFait tourner l'objet autour de l'axe vertical "
                                   "(affichage et export).", name="btn_turn")
        self.btn_flip = IconButton("rotate-3d", "Redresser\nBascule l'objet de 90° vers l'avant : utile s'il apparaît "
                                   "couché (affichage et export).", name="btn_flip")
        self.btn_wire = IconButton("box", "Afficher le maillage", checkable=True, name="btn_wire")
        self.btn_help = IconButton("circle-help", "Aide : les gestes de la souris", checkable=True, name="btn_help")
        self.btn_full = IconButton("maximize", "Plein écran (F11)", name="btn_full")
        for b in (self.btn_spin, self.btn_turn, self.btn_flip, self.btn_wire, self.btn_help, self.btn_full):
            tb.addWidget(b)
        self.btn_help.toggled.connect(lambda _on: self._layout_overlays())
        self.btn_full.clicked.connect(self.fullscreenRequested)

        # gestes (bas centre)
        self.modebar = QFrame(self)
        self.modebar.setObjectName("floatBar")
        mb = QHBoxLayout(self.modebar)
        mb.setContentsMargins(4, 4, 4, 4)
        mb.setSpacing(2)
        self.mode_buttons: dict[str, QToolButton] = {}
        for key, icon_name, label, tip in (
            ("rotate", "rotate-3d", "Faire pivoter", "Faire pivoter : clic gauche + glisser"),
            ("pan", "move", "Déplacer", "Déplacer : clic gauche + glisser (ou clic milieu)"),
            ("zoom", "zoom-in", "Zoom", "Zoom : clic gauche + glisser (ou molette)"),
        ):
            b = self._mode_button(icon_name, label, tip, checkable=True, name=f"btn_mode_{key}")
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self.mode_buttons[key] = b
            mb.addWidget(b)
        divider = QFrame()
        divider.setObjectName("separator")
        divider.setFixedWidth(1)
        divider.setMinimumHeight(24)
        divider.setMaximumHeight(28)
        mb.addWidget(divider)
        self.btn_reset = self._mode_button("house", "Réinitialiser", "Recentrer la vue (Ctrl+0)", checkable=False,
                                           name="btn_reset")
        mb.addWidget(self.btn_reset)
        self._compact = False
        self.mode_buttons["rotate"].setChecked(True)

        # choix de variante (bas droite) : seulement quand plusieurs variantes ont été générées
        self.variant_bar = QFrame(self)
        self.variant_bar.setObjectName("floatBar")
        vb = QHBoxLayout(self.variant_bar)
        vb.setContentsMargins(14, 4, 4, 4)
        vb.setSpacing(10)
        self.lbl_variant = QLabel("Variante")
        self.lbl_variant.setProperty("role", "label")
        self.seg_variant = Segmented(accessible_name="Variante affichée")
        vb.addWidget(self.lbl_variant)
        vb.addWidget(self.seg_variant)
        self._variants_shown = False
        self.toast = Toast(self)
        self._page = self.EMPTY
        self.viewer.interacted.connect(lambda: self.particles.pause_for(0.8))
        self.show_page(self.EMPTY)
        theme.bus.changed.connect(self._layout_overlays)

    def _mode_button(self, icon_name: str, label: str, tip: str, checkable: bool, name: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("modeBtn")
        b.setText(label)
        b.setToolTip(tip)
        b.setAccessibleName(label)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        icons.bind_icon(b, icon_name, "text-secondary", active="accent-text")
        b.setProperty("fullName", name)
        b.setObjectName("modeBtn")
        return b

    # ---- état ---------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self.viewer.set_mode(mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)

    def mode(self) -> str:
        return self.viewer.mode

    def set_info(self, text: str) -> None:
        self._info_full = text
        self.info.setToolTip(text)
        self.info.setText(text)
        self._layout_overlays()

    def set_fullscreen_state(self, on: bool) -> None:
        self.btn_full.setToolTip("Quitter le plein écran (F11 ou Échap)" if on else "Plein écran (F11)")
        self.btn_full.setAccessibleName("Quitter le plein écran" if on else "Plein écran")
        icons.rebind_icon(self.btn_full, "minimize" if on else "maximize", "text", active="accent-text")

    def page_name(self) -> str:
        return self._page

    def show_variants(self, shown: bool) -> None:
        self._variants_shown = shown
        self.variant_bar.setVisible(shown and self._page == self.RESULT)
        self._layout_overlays()

    def show_page(self, name: str) -> None:
        self._page = name
        self.stack.setCurrentWidget(self._pages[name])
        result = name == self.RESULT
        for w in (self.info, self.toolbar, self.modebar):
            w.setVisible(result)
        self.help.setVisible(result and self.btn_help.isChecked())
        self.variant_bar.setVisible(result and self._variants_shown)
        self.particles.set_mode("orbit" if result else "drift")
        self.particles.setVisible(name in (self.EMPTY, self.RESULT))
        if name != self.RESULT:
            self.reveal.stop()
        self._layout_overlays()
        QWidget.update(self)

    def play_reveal(self, pixmap: QPixmap | None) -> bool:
        """Transition de l'image vers le modèle (voir RevealOverlay)."""
        return self.reveal.start(pixmap)

    # ---- dessin du cadre ----------------------------------------------------
    def _frame_path(self, inset: float):
        c = current().px(20)
        return fx.chamfer_path(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), tl=c, br=c)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._frame_path(2.0)
        if not Motion.effects_off:
            fx.glow_stroke(p, path, t.color("violet"), 2.6, 0.9)
        base = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        base.setColorAt(0.0, t.color("bg-viewport"))
        base.setColorAt(1.0, t.color("bg-deep"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(base))
        p.drawPath(path)
        if self._page != self.RESULT:
            self._paint_stage(p, t)
        border = QLinearGradient(QPointF(0, 0), QPointF(self.width(), self.height()))
        border.setColorAt(0.0, t.color("violet-hover"))
        border.setColorAt(0.5, t.color("violet-deep"))
        border.setColorAt(1.0, t.color("accent"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(border), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
        p.drawPath(path)

    def _paint_stage(self, p: QPainter, t) -> None:
        """Décor des pages sans modèle : lueur au centre et sol en perspective qui fuit vers l'horizon."""
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w / 2, h * 0.46), max(w, h) * 0.5)
        glow.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.16))
        glow.setColorAt(1.0, fx.with_alpha(t.color("violet"), 0.0))
        p.save()
        p.setClipPath(self._frame_path(2.0))
        p.fillRect(self.rect(), QBrush(glow))
        horizon = h * 0.62
        p.setPen(QPen(fx.with_alpha(t.color("violet"), 0.22), 1))
        for k in range(1, 9):  # lignes horizontales de plus en plus espacées vers le bas
            y = horizon + (h - horizon) * (k / 8) ** 2
            p.drawLine(QPointF(0, y), QPointF(w, y))
        for k in range(-10, 11):  # lignes qui convergent vers le point de fuite
            p.drawLine(QPointF(w / 2 + k * w * 0.012, horizon), QPointF(w / 2 + k * w * 0.1, h))
        fade = QLinearGradient(QPointF(0, horizon), QPointF(0, horizon + h * 0.12))
        fade.setColorAt(0.0, fx.with_alpha(t.color("bg-viewport"), 1.0))
        fade.setColorAt(1.0, fx.with_alpha(t.color("bg-viewport"), 0.0))
        p.fillRect(QRectF(0, horizon - 1, w, h * 0.12 + 1), QBrush(fade))
        p.restore()

    # ---- disposition --------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlays()

    def _set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in (*self.mode_buttons.values(), self.btn_reset):
            b.setToolButtonStyle(style)

    def _layout_overlays(self) -> None:
        t = current()
        w, h = self.width(), self.height()
        inset = t.px(3)
        self.stack.setGeometry(inset, inset, w - 2 * inset, h - 2 * inset)
        c = t.px(20)  # le contenu suit les coins coupés du cadre
        poly = QPolygon([QPoint(c, 0), QPoint(w - 2 * inset, 0), QPoint(w - 2 * inset, h - 2 * inset - c),
                         QPoint(w - 2 * inset - c, h - 2 * inset), QPoint(0, h - 2 * inset), QPoint(0, c)])
        self.stack.setMask(QRegion(poly))
        self.particles.setGeometry(inset, inset, w - 2 * inset, h - 2 * inset)
        self.reveal.setGeometry(self.rect())
        m = t.px(18)
        result = self._page == self.RESULT

        # bas : la barre de gestes d'abord, en icônes seules si la largeur manque
        self._set_compact(False)
        self.modebar.adjustSize()
        if self.modebar.width() > w - 2 * m:
            self._set_compact(True)
            self.modebar.adjustSize()
        self.variant_bar.adjustSize()
        self.toolbar.adjustSize()
        self.modebar.move(max((w - self.modebar.width()) // 2, 0), h - self.modebar.height() - m)
        bottoms = [h - self.modebar.y()] if self.modebar.isVisible() else [0]
        # le choix de variante va à droite, ou au-dessus des gestes si les deux se toucheraient
        vx = w - self.variant_bar.width() - m
        vy = h - self.variant_bar.height() - m
        if self.variant_bar.isVisible():
            if vx < self.modebar.x() + self.modebar.width() + m:
                vx = max((w - self.variant_bar.width()) // 2, 0)
                vy = self.modebar.y() - self.variant_bar.height() - t.px(8)
            self.variant_bar.move(vx, vy)
            bottoms.append(h - vy)

        # haut : outils à droite, pastille d'information à gauche (coupée si la place manque), aide sous les outils
        self.toolbar.move(max(w - self.toolbar.width() - m, 0), m)
        room = self.toolbar.x() - 2 * m
        fm = self.info.fontMetrics()
        pill_pad = t.px(2 * 12 + 4)
        if self._info_full and room > t.px(110):
            # on retire les derniers éléments (« · 1024 », « · TRELLIS.2 »…) plutôt que de couper un mot : l'essentiel vient en premier
            parts = self._info_full.split(" · ")
            while len(parts) > 1 and fm.horizontalAdvance(" · ".join(parts)) > room - pill_pad:
                parts.pop()
            self.info.setText(fm.elidedText(" · ".join(parts), Qt.TextElideMode.ElideRight, room - pill_pad))
        else:
            self.info.setText(self._info_full)
        self.info.adjustSize()
        self.info.move(m, m + (self.toolbar.height() - self.info.height()) // 2)
        self.info.setVisible(result and bool(self._info_full) and room > t.px(110))
        self.help.setFixedWidth(min(t.px(320), max(w - 2 * m, 100)))
        self.help.adjustSize()
        self.help.move(max(w - self.help.width() - m, 0), m + self.toolbar.height() + t.px(8))
        self.help.setVisible(result and self.btn_help.isChecked())

        self.toast.reposition(max(max(bottoms), 0))
        for widget in (self.particles, self.info, self.help, self.toolbar, self.modebar, self.variant_bar, self.reveal, self.toast):
            widget.raise_()
        if not self.reveal.isVisible():
            self.reveal.lower()
            self.particles.raise_()
            for widget in (self.info, self.help, self.toolbar, self.modebar, self.variant_bar, self.toast):
                widget.raise_()
