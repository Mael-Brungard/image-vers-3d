"""
pages.py - les deux pages à côté du studio : « Mes créations » (modèles déjà enregistrés) et « Paramètres ».

Rien d'inventé : « Mes créations » liste de vrais fichiers (voir creations.py) et « Paramètres » réunit les réglages qui
existaient déjà (taille du texte, animations, journal, licences, prompt d'image) plus l'interrupteur des effets visuels.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from . import fx, icons, theme
from .creations import Creation, CreationStore, format_size, format_when
from .theme import current
from .widgets import ElidedLabel, HaloIcon, Segmented, Switch, make_button, text_label


# --------------------------------------------------------------------------------------------------------------------
#  Mes créations
# --------------------------------------------------------------------------------------------------------------------
class Thumb(QWidget):
    """Vignette d'une création : l'image de départ, recadrée dans un cadre à coins coupés ; sans image, une icône de cube."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.bus.changed.connect(self._refit)
        self._refit()

    def _refit(self) -> None:
        self.setFixedHeight(current().px(150))

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen

        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = fx.chamfer_path(box, tl=t.px(10), br=t.px(10))
        fill = QLinearGradient(box.topLeft(), box.bottomRight())
        fill.setColorAt(0.0, t.color("violet-soft"))
        fill.setColorAt(1.0, t.color("bg-viewport"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        if self._pixmap is not None and not self._pixmap.isNull():
            p.save()
            p.setClipPath(path)
            scaled = self._pixmap.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            target = QRectF(box.center().x() - scaled.width() / 2, box.center().y() - scaled.height() / 2,
                            scaled.width(), scaled.height())
            p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
            p.restore()
        else:
            size = t.px(40)
            p.drawPixmap(QRectF(box.center().x() - size / 2, box.center().y() - size / 2, size, size).toRect(),
                         icons.pixmap("box", t["violet-text"], size))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(fx.with_alpha(t.color("violet"), 0.8), 1.2))
        p.drawPath(path)


class CreationCard(fx.Panel):
    """Une création : vignette, nom, faits (format, moteur, taille, date) et actions."""

    openRequested = Signal(str)  # chemin du modèle
    folderRequested = Signal(str)
    removeRequested = Signal(str)  # identifiant

    def __init__(self, creation: Creation, store: CreationStore, parent: QWidget | None = None) -> None:
        super().__init__("violet", parent, margin=12, cut=12)
        self.creation = creation
        self.setObjectName("creationCard")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        v = self.vbox(8)
        self.thumb = Thumb()
        thumb_path = store.thumb_path(creation)
        if thumb_path is not None:
            self.thumb.set_pixmap(QPixmap(str(thumb_path)))
        v.addWidget(self.thumb)
        self.name = ElidedLabel(creation.name)
        self.name.setObjectName("panelTitle")
        v.addWidget(self.name)
        facts = " · ".join(x for x in (creation.format.upper(), creation.engine, format_size(creation.size) if creation.size else "") if x)
        self.facts = ElidedLabel(facts)
        self.facts.setProperty("role", "caption")
        v.addWidget(self.facts)
        self.when = ElidedLabel(format_when(creation.created))
        self.when.setProperty("role", "muted")
        v.addWidget(self.when)
        if creation.info:
            self.info = ElidedLabel(creation.info)
            self.info.setProperty("role", "muted")
            v.addWidget(self.info)
        self.missing = not creation.exists()
        if self.missing:
            warn = text_label("Fichier introuvable : il a été déplacé ou supprimé.", role="danger", wrap=True)
            v.addWidget(warn)
        for label in (self.name, self.facts, self.when, getattr(self, "info", None)):
            if label is not None:  # une ligne de texte garde sa hauteur : l'espace en trop va au-dessus des boutons
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        v.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_open = make_button("Ouvrir", icon="external-link", name="btn_creation_open")
        self.btn_folder = make_button("", kind="ghost", icon="folder-open", name="btn_creation_folder", icon_role="text-secondary")
        self.btn_remove = make_button("", kind="ghost", icon="trash-2", name="btn_creation_remove", icon_role="text-secondary")
        for button, tip in ((self.btn_open, "Ouvrir le modèle avec le programme que Windows associe à ce type de fichier"),
                            (self.btn_folder, "Afficher le dossier du fichier"),
                            (self.btn_remove, "Retirer de la liste (le fichier n'est pas supprimé)")):
            button.setToolTip(tip)
            button.setAccessibleName(tip.split(" (")[0])
        for button in (self.btn_folder, self.btn_remove):
            button.setFixedWidth(current().px(48))
        self.btn_open.setEnabled(not self.missing)
        self.btn_open.clicked.connect(lambda: self.openRequested.emit(creation.path))
        self.btn_folder.clicked.connect(lambda: self.folderRequested.emit(creation.path))
        self.btn_remove.clicked.connect(lambda: self.removeRequested.emit(creation.id))
        row.addWidget(self.btn_open, 1)
        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_remove)
        v.addLayout(row)
        theme.bus.changed.connect(self._refit)
        self._refit()

    def _refit(self) -> None:
        t = current()
        self.setFixedWidth(t.px(268))
        layout = self.layout()
        layout.activate()
        inner = t.px(268) - self.contentsMargins().left() - self.contentsMargins().right()
        height = layout.totalHeightForWidth(inner) if layout.hasHeightForWidth() else layout.sizeHint().height()
        self.setFixedHeight(height + self.contentsMargins().top() + self.contentsMargins().bottom())
        for button in (self.btn_folder, self.btn_remove):
            button.setFixedWidth(t.px(48))


class CreationsPage(QWidget):
    """Page « Mes créations » : grille de cartes qui passe à la ligne selon la largeur ; message d'accueil quand elle est vide."""

    openRequested = Signal(str)
    folderRequested = Signal(str)

    def __init__(self, store: CreationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparent")
        self.store = store
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 16, 24, 16)
        v.setSpacing(12)
        head = QHBoxLayout()
        self.title = text_label("Mes créations", name="title")
        self.count = text_label("", role="muted")
        head.addWidget(self.title)
        head.addSpacing(12)
        head.addWidget(self.count)
        head.addStretch(1)
        v.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("scrollBody")
        self.grid = fx.FlowLayout(self.grid_host, 16, 16)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.scroll.setWidget(self.grid_host)
        v.addWidget(self.scroll, 1)
        # état vide
        self.empty = QWidget()
        self.empty.setObjectName("transparent")
        ev = QVBoxLayout(self.empty)
        ev.addStretch(1)
        self.halo = HaloIcon(112, "images")
        ev.addWidget(self.halo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = text_label("Aucune création pour le moment", name="title")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setWordWrap(True)
        ev.addWidget(self.empty_title)
        self.empty_text = text_label("Les modèles que tu enregistres avec « Enregistrer sous… » apparaissent ici, avec leur "
                                     "vignette. Retirer une carte ne supprime jamais le fichier.", role="secondary", wrap=True)
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text.setMaximumWidth(current().px(520))
        # centré par deux ressorts : un alignement de layout ignorerait la hauteur du texte qui passe à la ligne
        text_row = QHBoxLayout()
        text_row.addStretch(1)
        text_row.addWidget(self.empty_text, 100)
        text_row.addStretch(1)
        ev.addLayout(text_row)
        ev.addStretch(2)
        v.addWidget(self.empty, 1)
        theme.bus.changed.connect(lambda: self.empty_text.setMaximumWidth(current().px(520)))
        theme.bus.changed.connect(lambda: QTimer.singleShot(0, self._equalize))  # après le recalcul de chaque carte
        self.cards: list[CreationCard] = []
        self.refresh()

    def refresh(self) -> None:
        for card in self.cards:
            self.grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        items = self.store.load()
        for creation in items:
            card = CreationCard(creation, self.store)
            card.openRequested.connect(self.openRequested)
            card.folderRequested.connect(self.folderRequested)
            card.removeRequested.connect(self._remove)
            self.grid.addWidget(card)
            self.cards.append(card)
        self._equalize()
        self.count.setText(f"{len(items)} modèle{'s' if len(items) > 1 else ''}" if items else "")
        self.scroll.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.grid_host.updateGeometry()

    def _equalize(self) -> None:
        """Toutes les cartes ont la hauteur de la plus haute : les boutons s'alignent d'une carte à l'autre."""
        if self.cards:
            tallest = max(card.height() for card in self.cards)
            for card in self.cards:
                card.setFixedHeight(tallest)

    def _remove(self, ident: str) -> None:
        self.store.remove(ident)
        self.refresh()


# --------------------------------------------------------------------------------------------------------------------
#  Paramètres
# --------------------------------------------------------------------------------------------------------------------
class SettingsPage(QWidget):
    """Page « Paramètres » : affichage (taille du texte, animations, effets), calcul (carte graphique, dossier des données),
    aide (prompt d'image, journal, licences) et à propos."""

    scaleChanged = Signal(float)
    reduceMotionChanged = Signal(bool)
    effectsChanged = Signal(bool)
    openLogRequested = Signal()
    openLicencesRequested = Signal()
    openDataRequested = Signal()
    copyPromptRequested = Signal()

    SCALES = ((1.0, "100 %"), (1.15, "115 %"), (1.3, "130 %"))

    def __init__(self, version: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparent")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)
        outer.addWidget(text_label("Paramètres", name="title"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.columns = fx.FlowLayout(body, 16, 16, centered=True)
        self.columns.setContentsMargins(6, 6, 6, 6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # --- affichage
        display = self._panel("Affichage")
        v = display.layout()
        v.addWidget(text_label("Taille du texte", role="label"))
        self.seg_scale = Segmented(accessible_name="Taille du texte")
        for value, label in self.SCALES:
            self.seg_scale.addItem(label, value)
        self.seg_scale.currentIndexChanged.connect(lambda i: self.scaleChanged.emit(self.seg_scale.itemData(i)))
        v.addWidget(self.seg_scale)
        self.sw_motion = Switch("Réduire les animations")
        self.sw_motion.setToolTip("Coupe tous les mouvements. Windows peut aussi le demander "
                                  "(Paramètres > Accessibilité > Effets visuels).")
        self.sw_motion.toggled.connect(self.reduceMotionChanged)
        v.addWidget(self.sw_motion)
        self.sw_effects = Switch("Effets visuels")
        self.sw_effects.setToolTip("Halos, particules, robot animé et transitions. Les couper laisse une interface "
                                   "plus sobre ; rien d'autre ne change.")
        self.sw_effects.toggled.connect(self.effectsChanged)
        v.addWidget(self.sw_effects)

        # --- calcul
        compute = self._panel("Calcul")
        v = compute.layout()
        v.addWidget(text_label("Carte graphique détectée", role="label"))
        self.device = text_label("", wrap=True)
        v.addWidget(self.device)
        note = text_label("Tout le calcul se fait sur cet ordinateur : tes images et tes modèles ne sont envoyés nulle part.",
                          role="muted", wrap=True)
        v.addWidget(note)
        self.btn_data = make_button("Ouvrir le dossier des données", icon="folder-open", name="btn_data")
        self.btn_data.setToolTip("Modèles d'IA téléchargés, moteur Qualité maximale, journal et liste de tes créations.")
        self.btn_data.clicked.connect(self.openDataRequested)
        v.addWidget(self.btn_data)

        # --- aide
        helpp = self._panel("Aide")
        v = helpp.layout()
        self.btn_prompt = make_button("Copier le prompt ChatGPT", kind="ghost", icon="copy", icon_role="text-secondary",
                                      name="btn_prompt")
        self.btn_prompt.setToolTip("Texte à coller dans ChatGPT (ou un autre générateur d'images) pour obtenir une image de "
                                   "départ idéale pour la 3D.")
        self.btn_log = make_button("Ouvrir le journal", kind="ghost", icon="file-text", icon_role="text-secondary", name="btn_log")
        self.btn_licences = make_button("Licences et crédits", kind="ghost", icon="info", icon_role="text-secondary",
                                        name="btn_licences")
        self.btn_prompt.clicked.connect(self.copyPromptRequested)
        self.btn_log.clicked.connect(self.openLogRequested)
        self.btn_licences.clicked.connect(self.openLicencesRequested)
        for b in (self.btn_prompt, self.btn_log, self.btn_licences):
            b.setProperty("align", "left")
            v.addWidget(b)

        # --- à propos
        about = self._panel("À propos")
        v = about.layout()
        v.addWidget(fx.Logo(52, tagline=True), 0, Qt.AlignmentFlag.AlignLeft)
        self.version = text_label(version, role="muted")
        v.addWidget(self.version)
        v.addWidget(text_label("Transforme une image en modèle 3D, entièrement sur ton ordinateur.", role="secondary", wrap=True))

    def _panel(self, title: str) -> fx.Panel:
        panel = fx.Panel("violet", margin=18)
        panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        v = panel.vbox(10)
        v.addWidget(fx.PanelHeader(title))
        self._fit(panel)
        theme.bus.changed.connect(lambda p=panel: self._fit(p))
        self.columns.addWidget(panel)
        return panel

    @staticmethod
    def _fit(panel: fx.Panel) -> None:
        panel.setFixedWidth(current().px(380))
        panel.setMinimumHeight(0)

    def set_state(self, scale: float, reduce_motion: bool, effects: bool) -> None:
        for widget in (self.seg_scale, self.sw_motion, self.sw_effects):
            widget.blockSignals(True)
        self.seg_scale.setCurrentIndex(next((i for i, (k, _) in enumerate(self.SCALES) if abs(k - scale) < 1e-6), 0))
        self.sw_motion.setChecked(reduce_motion)
        self.sw_effects.setChecked(effects)
        for widget in (self.seg_scale, self.sw_motion, self.sw_effects):
            widget.blockSignals(False)

    def set_device(self, text: str) -> None:
        self.device.setText(text or "Non détectée")
