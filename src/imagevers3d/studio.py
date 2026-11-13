#!/usr/bin/env python3
"""
studio.py - « Image vers 3D » : application de bureau, 100 % locale.

Glisse une image dans la fenêtre, clique sur « Générer la 3D », tourne le
modèle à la souris, puis enregistre-le en .glb ou .obj.

L'apparence (thèmes, composants, états) est définie dans theme.py et widgets.py ; voir docs/DESIGN.md.

Lancement :  python -m imagevers3d   (ou le raccourci « Image vers 3D » du menu Démarrer)
"""

from __future__ import annotations

import sys

# Sans console (pythonw.exe : raccourci du menu Démarrer), sys.stdout et sys.stderr valent
# None. Toute bibliothèque qui écrit dedans (barres de progression du téléchargement des
# modèles, avertissements...) plante alors avec « 'NoneType' object has no attribute 'write' ».
# On les redirige vers un fichier, avant d'importer quoi que ce soit d'autre.
if sys.stdout is None or sys.stderr is None:
    from . import paths as _paths

    _paths.ensure_user_dirs()
    _console = open(_paths.CONSOLE_LOG_FILE, "w", encoding="utf-8", errors="replace", buffering=1)
    if sys.stdout is None:
        sys.stdout = _console
    if sys.stderr is None:
        sys.stderr = _console

import logging
import traceback
from dataclasses import dataclass
from pathlib import Path

# PyTorch doit être importé AVANT Qt : sous Windows, l'ordre inverse peut
# provoquer des conflits de DLL au chargement. (Le démarrage prend donc
# quelques secondes avant l'apparition de la fenêtre.)
try:
    import torch
except ImportError:  # message clair affiché dans main()
    torch = None

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__, paths, theme
from . import license as licensing
from ._licproto import TRIAL_DAYS, LicenseError
from .geometry import IDENTITY, ORIENTATION, display_arrays, rotation
from .license_ui import LicenseChip, LicenseGate
from .mesh_tools import prepare_for_export
from .theme import Motion
from .triposg_runner import INSTALL_HINT, TripoSGRunner
from .widgets import (
    BusyState,
    DropZone,
    ElidedLabel,
    EmptyState,
    ErrorPanel,
    HardwareChip,
    IconButton,
    IndeterminateBar,
    KeyCap,
    Segmented,
    SettingsPopover,
    Switch,
    Toast,
    make_button,
    qimage_to_pil,
    set_kind,
    text_label,
)

LOG_FILE = paths.LOG_FILE
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
QUALITIES = [("Rapide (128)", 128), ("Équilibré (192)", 192), ("Standard (256)", 256), ("Détaillé (320)", 320)]
DEFAULT_QUALITY_INDEX = 2
# Moteurs : identifiant, libellé. TripoSR est le moteur fourni. TripoSG n'est PAS distribué avec le logiciel (sa licence
# exclut l'Union européenne, voir docs/LICENSES.md) : il n'est proposé que s'il est déjà présent sur l'ordinateur.
ENGINES = [
    ("triposr", "TripoSR : rapide, couleurs estimées"),
    ("triposg", "TripoSG : forme fine, couleurs de ton image"),
]
QUALITIES_SG = [("Rapide (25 étapes)", 25), ("Standard (50 étapes)", 50), ("Soigné (80 étapes)", 80)]
DEFAULT_QUALITY_INDEX_SG = 1

log = logging.getLogger("studio")


# =============================================================================
#  Moteur : TripoSR + retrait du fond (chargé à la demande, hors du fil de l'interface)
# =============================================================================
class Engine:
    """Fait le lien entre l'interface et image_to_3d.py."""

    def __init__(self) -> None:
        self._i3d = None
        self.model = None
        self.device = None
        self.session = None
        self.triposg = TripoSGRunner()

    def triposg_ready(self) -> bool:
        return self.triposg.available()

    def device_label(self) -> str:
        if torch is None:
            return "PyTorch introuvable"
        if torch.cuda.is_available():
            return f"GPU : {torch.cuda.get_device_name(0)}"
        return "Processeur (lent : aucun GPU CUDA détecté)"

    def _module(self):
        if self._i3d is None:
            from . import image_to_3d  # lourd : charge TripoSR

            self._i3d = image_to_3d
        return self._i3d

    def _ensure_model(self, progress) -> None:
        i3d = self._module()
        if self.model is None:
            progress("Chargement du modèle 3D (le tout premier lancement télécharge environ 1,5 Go)…")
            self.model, self.device = i3d.load_model("auto", 8192)

    def _rembg_session(self, remove_bg: bool, progress):
        if remove_bg and self.session is None:
            progress("Préparation du détourage (téléchargement au premier usage)…")
            self.session = self._module().new_rembg_session()
        return self.session

    def preprocess(self, image: Image.Image, remove_bg: bool, ratio: float, progress) -> Image.Image:
        """TripoSR : objet centré sur fond gris uni."""
        licensing.require()
        session = self._rembg_session(remove_bg, progress)
        progress("Détourage de l'image…" if remove_bg else "Préparation de l'image…")
        return self._module().preprocess(image, remove_bg, ratio, session)

    def prepare_triposg(self, image: Image.Image, remove_bg: bool, ratio: float, progress):
        """TripoSG : renvoie (objet centré sur fond blanc, objet détouré en RGBA pour les couleurs)."""
        licensing.require()
        session = self._rembg_session(remove_bg, progress)
        progress("Détourage de l'image…" if remove_bg else "Préparation de l'image…")
        cut = self._module().cutout(image, remove_bg, ratio, session)
        white = Image.new("RGB", cut.size, (255, 255, 255))
        white.paste(cut, mask=cut.getchannel("A"))
        return white, cut

    def generate(self, prepared: Image.Image, resolution: int, progress):
        licensing.require()
        self._ensure_model(progress)
        progress("Génération du modèle 3D…")
        try:
            return self._module().generate_mesh(self.model, prepared, self.device, resolution)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            raise RuntimeError(
                "Mémoire GPU insuffisante. Choisis une qualité plus basse "
                "(Rapide ou Équilibré) et réessaie."
            ) from None

    def generate_triposg(self, prepared: Image.Image, steps: int, progress, seed: int = 42, cutout: Image.Image | None = None):
        """Renvoie (maillage d'aperçu, maillage complet, remarques) ; calcul dans le processus de TripoSG."""
        licensing.require()
        return self.triposg.generate(prepared, steps, progress, seed=seed, cutout=cutout)

    def export_triposg(self, result: dict, path: Path, progress) -> Path:
        licensing.require()
        progress("Export du fichier…")
        mesh = result["mesh_export"].copy()
        transform = np.eye(4)
        transform[:3, :3] = result["extra"]  # corrections d'orientation faites à la main
        mesh.apply_transform(transform)
        # normales lisses, couleurs linéaires (glTF), métadonnées sans chemin local
        mesh = prepare_for_export(mesh, glb=Path(path).suffix.lower() == ".glb")
        path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(path))
        return path

    def export(self, mesh, scene_codes, path: Path, bake: bool, progress) -> Path:
        licensing.require()
        progress("Export du fichier (la texture peut prendre quelques secondes)…" if bake else "Export du fichier…")
        # L'export applique une rotation sur place : on travaille sur une copie
        # pour pouvoir exporter plusieurs fois le même résultat.
        return self._module().export_mesh(self.model, mesh.copy(), scene_codes, path, bake)


# =============================================================================
#  Tâches en arrière-plan
# =============================================================================
LICENSE_FAILURE = "license"  # valeur de « détails » d'un échec dû à la licence (voir MainWindow._task_failed)


class TaskSignals(QObject):
    progress = Signal(str)
    partial = Signal(object)
    finished = Signal(object)
    failed = Signal(str, str)  # message court, trace complète


class Task(QRunnable):
    """Exécute fn(progress, partial) hors du fil de l'interface."""

    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit, self.signals.partial.emit)
        except LicenseError as exc:  # la licence a pris fin pendant le travail : l'écran Licence s'affiche, pas un message d'erreur
            self.signals.failed.emit(exc.message, LICENSE_FAILURE)
        except BaseException as exc:  # noqa: BLE001 - y compris SystemExit de l'import du moteur
            details = traceback.format_exc()
            log.error("Tâche en échec :\n%s", details)
            # Nos propres messages (RuntimeError) sont déjà rédigés pour l'utilisateur ;
            # pour le reste, le type d'erreur aide à comprendre.
            message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
            self.signals.failed.emit(message, details)
        else:
            self.signals.finished.emit(result)




# =============================================================================
#  Visionneuse 3D
# =============================================================================
class MeshViewer(QStackedWidget):
    """Visionneuse 3D (pyqtgraph/OpenGL) : clic gauche = tourner, molette = zoom, clic milieu = déplacer."""

    CAMERA = dict(distance=3.4, elevation=18, azimuth=-90)
    SPIN_DEGREES = 0.45  # par image (~27°/s)
    EDGE_COLOR = {"dark": (0.05, 0.06, 0.09, 1.0), "light": (0.16, 0.18, 0.22, 1.0)}

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
        self._last: tuple | None = None  # (maillage, orientation) pour redessiner quand le thème change
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._spin_step)

    def _ensure_view(self) -> bool:
        if self._view is not None:
            return True
        try:
            import pyqtgraph.opengl as gl

            self._gl = gl
            self._view = gl.GLViewWidget()
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
                    self._grid.setColor(t.color("border-strong", 0.45))
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


class ViewportFrame(QFrame):
    """Zone centrale : une page à la fois (vide, calcul, résultat, erreur) et, par-dessus, les commandes flottantes."""

    EMPTY, BUSY, RESULT, ERROR = "empty", "busy", "result", "error"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("viewport")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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

        # commandes flottantes (visibles seulement avec un résultat)
        self.info = QLabel("", self)
        self.info.setObjectName("infoPill")
        self.help = QLabel("Clic gauche : tourner · Molette : zoom · Clic milieu : déplacer", self)
        self.help.setObjectName("infoPill")
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("floatBar")
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(4, 4, 4, 4)
        tb.setSpacing(2)
        self.btn_reset = IconButton("house", "Recentrer la vue (Ctrl+0)", name="btn_reset")
        self.btn_wire = IconButton("grid-3x3", "Afficher le maillage", checkable=True, name="btn_wire")
        self.btn_spin = IconButton("orbit", "Faire tourner automatiquement", checkable=True, name="btn_spin")
        self.btn_turn = IconButton("rotate-cw", "Pivoter de 90°\nFait tourner l'objet autour de l'axe vertical "
                                   "(affichage et export).", name="btn_turn")
        self.btn_flip = IconButton("rotate-3d", "Redresser\nBascule l'objet de 90° vers l'avant : utile s'il apparaît "
                                   "couché (affichage et export).", name="btn_flip")
        for b in (self.btn_reset, self.btn_wire, self.btn_spin, self.btn_turn, self.btn_flip):
            tb.addWidget(b)
        self.toast = Toast(self)
        self._page = self.EMPTY
        self.show_page(self.EMPTY)
        theme.bus.changed.connect(self._layout_overlays)

    def page_name(self) -> str:
        return self._page

    def show_page(self, name: str) -> None:
        self._page = name
        self.stack.setCurrentWidget(self._pages[name])
        result = name == self.RESULT
        for w in (self.info, self.help, self.toolbar):
            w.setVisible(result)
        self._layout_overlays()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlays()

    def _layout_overlays(self) -> None:
        self.stack.setGeometry(self.rect())
        m = theme.current().px(16)
        self.info.adjustSize()
        self.help.adjustSize()
        self.toolbar.adjustSize()
        self.info.move(m, m)
        self.toolbar.move(self.width() - self.toolbar.width() - m, m)
        self.help.move(m, self.height() - self.help.height() - m)
        # sur une fenêtre étroite, l'aide passe sous la barre d'outils plutôt que de la recouvrir
        self.help.setVisible(self._page == self.RESULT and self.width() > self.help.width() + 2 * m)
        reserved = (self.help.height() + m) if self.help.isVisible() else 0
        self.toast.reposition(reserved)
        for w in (self.info, self.help, self.toolbar):
            w.raise_()
        self.toast.raise_()


# =============================================================================
#  Fenêtre principale
# =============================================================================
@dataclass
class Options:
    remove_bg: bool
    ratio: float
    resolution: int  # TripoSR : finesse du maillage ; TripoSG : nombre d'étapes
    engine: str = "triposr"
    colorize: bool = True  # TripoSG : colorier la forme d'après l'image
    seed: int = 42  # TripoSG : numéro de variante


# Explication courte sous le sélecteur de qualité : ce que le réglage change.
QUALITY_HINTS = {
    ("triposr", 128): "Maillage 128 : le plus rapide, détails simplifiés.",
    ("triposr", 192): "Maillage 192 : rapide, détails corrects.",
    ("triposr", 256): "Maillage 256 : recommandé, bon équilibre vitesse et détail.",
    ("triposr", 320): "Maillage 320 : le plus fin, plus lent, plus de mémoire GPU.",
    ("triposg", 25): "25 étapes : brouillon rapide.",
    ("triposg", 50): "50 étapes : recommandé.",
    ("triposg", 80): "80 étapes : le plus soigné, le plus lent.",
}
FAILURE_TITLES = {
    "generate": "La génération a échoué",
    "preview": "Le détourage a échoué",
    "save": "L'enregistrement a échoué",
}
FAILURE_HINT = "Réessaie. Si le problème continue, copie les détails et ouvre le journal : ils expliquent ce qui s'est passé."
TOAST_SECONDS = 5000
LICENSE_CHECK_MS = 60_000  # la licence est revérifiée chaque minute (fin d'essai, horloge) en plus des contrôles avant chaque calcul
OBJ_TIP = "Crée une vraie image de texture. Plus propre dans Blender, mais l'export est plus long."


class MainWindow(QMainWindow):
    def __init__(self, engine, settings: QSettings | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings if settings is not None else QSettings("ImageVers3D", "Studio")
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self.input_image: Image.Image | None = None
        self.input_name = "modele"
        self.result: dict | None = None
        self.last_saved: Path | None = None
        self._task: Task | None = None
        self._task_kind: str | None = None
        self._on_done = None
        self._on_partial = None
        self._error: dict | None = None
        self._retry = None
        self._bake_pref = False
        self._syncing_format = False
        self._license_status: licensing.LicenseStatus | None = None
        self._gate_closable = False

        self.theme_pref = self.settings.value("theme", "dark", type=str)
        if self.theme_pref not in theme.THEME_MODES:
            self.theme_pref = "dark"
        scale = self.settings.value("text_scale", 1.0, type=float)
        self.text_scale = scale if scale in theme.TEXT_SCALES else 1.0
        self.reduce_motion = self.settings.value("reduce_motion", False, type=bool)
        Motion.refresh(self.reduce_motion)
        theme.apply_theme(QApplication.instance(), self.theme_pref, self.text_scale)

        self.setWindowTitle(APP_NAME if __version__.endswith("+dev") else f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        icon_path = paths.ASSETS_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self._apply_metrics()
        self._initial_size()
        self._restore_settings()
        self._bind_shortcuts()
        self.viewer.apply_theme()
        theme.bus.changed.connect(self._apply_metrics)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        except Exception:  # noqa: BLE001 - Qt plus ancien : le thème « Système » ne suit pas en direct
            pass
        self._refresh_ui()
        self.set_status("Prêt. Dépose une image dans la fenêtre pour commencer.")
        self._license_timer = QTimer(self)
        self._license_timer.setInterval(LICENSE_CHECK_MS)
        self._license_timer.timeout.connect(self._check_license)
        self._license_timer.start()
        self._check_license()

    # ---- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left())
        body.addWidget(self._build_right(), 1)
        outer.addLayout(body, 1)
        outer.addWidget(self._build_footer())

        self._root = root
        self.gate = LicenseGate()
        self.gate.setObjectName("root")  # même fond que la fenêtre
        self.gate.statusChanged.connect(self._license_changed)
        self.gate.closeRequested.connect(self._close_gate)
        self.stack = QStackedWidget()
        self.stack.addWidget(root)
        self.stack.addWidget(self.gate)
        self.setCentralWidget(self.stack)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        self._topbar = bar
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 12, 0)
        h.setSpacing(12)
        logo = QLabel()
        icon_png = paths.ASSETS_DIR / "icon.png"
        if icon_png.exists():
            logo.setPixmap(QPixmap(str(icon_png)).scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setFixedSize(32, 32)
        name = QLabel(APP_NAME)
        name.setObjectName("appName")
        version = text_label("développement" if __version__.endswith("+dev") else f"v{__version__}", role="muted")
        h.addWidget(logo)
        h.addWidget(name)
        h.addWidget(version)
        h.addStretch(1)
        self.chip_trial = LicenseChip()
        self.chip_trial.clicked.connect(self.on_open_license)
        h.addWidget(self.chip_trial)
        self.chip = HardwareChip()
        self.chip.set_device(self.engine.device_label())
        h.addWidget(self.chip)
        self.btn_menu = IconButton("ellipsis", "Réglages et aide", name="btn_menu")
        self.btn_menu.clicked.connect(self._open_menu)
        h.addWidget(self.btn_menu)
        self.menu = SettingsPopover(self)
        self.menu.themeChanged.connect(self._set_theme)
        self.menu.scaleChanged.connect(self._set_scale)
        self.menu.reduceMotionChanged.connect(self._set_reduce_motion)
        self.menu.openLicenseRequested.connect(self.on_open_license)
        self.menu.openLogRequested.connect(self.on_open_log)
        self.menu.openLicencesRequested.connect(self.on_open_licences)
        return bar

    def _build_left(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("leftPanel")
        self._left = panel
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        lv = QVBoxLayout(body)
        lv.setContentsMargins(20, 16, 20, 16)
        lv.setSpacing(10)
        scroll.setWidget(body)
        pv.addWidget(scroll, 1)

        lv.addWidget(text_label("Image", name="h2"))
        self.drop = DropZone()
        self.drop.openRequested.connect(self.on_open)
        self.drop.pasteRequested.connect(self.on_paste)
        self.drop.viewChanged.connect(self._on_view_changed)
        self.btn_open, self.btn_paste = self.drop.btn_open, self.drop.btn_paste
        lv.addWidget(self.drop)
        lv.addSpacing(8)

        lv.addWidget(text_label("Réglages", name="h2"))

        # moteur : seulement si TripoSG est déjà installé (il n'est pas distribué avec le logiciel)
        self.engine_row = QWidget()
        self.engine_row.setObjectName("transparent")
        ev = QVBoxLayout(self.engine_row)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        ev.addWidget(text_label("Moteur d'IA", role="label"))
        self.cmb_engine = QComboBox()
        self.cmb_engine.setAccessibleName("Moteur d'IA")
        for engine_id, label in ENGINES:
            if engine_id == "triposg" and not self.engine.triposg_ready():
                continue  # moteur non fourni : on ne le propose pas
            self.cmb_engine.addItem(label, engine_id)
        tooltip = "TripoSR : rapide, couleurs estimées par l'IA, forme approximative."
        if self.cmb_engine.count() > 1:
            tooltip += "\nTripoSG (expérimental) : forme beaucoup plus fine, colorée d'après ton image."
        self.cmb_engine.setToolTip(tooltip)
        ev.addWidget(self.cmb_engine)
        self.engine_row.setVisible(self.cmb_engine.count() > 1)
        lv.addWidget(self.engine_row)

        self.chk_bg = Switch("Retirer le fond")
        self.chk_bg.setChecked(True)
        self.chk_bg.setToolTip("Isole l'objet du décor avant de créer le modèle 3D.")
        lv.addWidget(self.chk_bg)

        ratio_head = QHBoxLayout()
        self.lbl_ratio_title = text_label("Taille de l'objet dans l'image", role="label")
        self.lbl_ratio = text_label("85 %", role="caption")
        self.lbl_ratio.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ratio_head.addWidget(self.lbl_ratio_title, 1)
        ratio_head.addWidget(self.lbl_ratio)
        lv.addLayout(ratio_head)
        self.sld_ratio = QSlider(Qt.Orientation.Horizontal)
        self.sld_ratio.setRange(50, 100)
        self.sld_ratio.setSingleStep(5)
        self.sld_ratio.setPageStep(5)
        self.sld_ratio.setValue(85)
        self.sld_ratio.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.sld_ratio.setAccessibleName("Taille de l'objet dans l'image, en pourcentage")
        self.sld_ratio.setToolTip("Part de l'image occupée par l'objet une fois recadré. Plus grand = plus de détails.")
        self.sld_ratio.valueChanged.connect(self._update_ratio_label)
        lv.addWidget(self.sld_ratio)

        self.lbl_quality = text_label("Qualité", role="label")
        lv.addWidget(self.lbl_quality)
        self.cmb_quality = Segmented(accessible_name="Qualité")
        lv.addWidget(self.cmb_quality)
        self.lbl_quality_hint = text_label("", role="muted", wrap=True)
        lv.addWidget(self.lbl_quality_hint)

        self.chk_color = Switch("Colorier d'après l'image")
        self.chk_color.setChecked(True)
        self.chk_color.setToolTip(
            "TripoSG ne donne que la forme. Cette option projette les couleurs de ton image sur le modèle ;\n"
            "le dos et les zones cachées sont estimés (ils peuvent être approximatifs)."
        )
        lv.addWidget(self.chk_color)
        self.seed_row = QWidget()
        self.seed_row.setObjectName("transparent")
        sl = QHBoxLayout(self.seed_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(text_label("Variante", role="label"), 1)
        self.spn_seed = QSpinBox()
        self.spn_seed.setRange(0, 9999)
        self.spn_seed.setValue(42)
        self.spn_seed.setAccessibleName("Numéro de variante")
        self.spn_seed.setToolTip("TripoSG invente ce que l'image ne montre pas : une autre variante donne un autre résultat.")
        sl.addWidget(self.spn_seed)
        lv.addWidget(self.seed_row)
        lv.addStretch(1)

        self._fill_quality("triposr")
        self.cmb_engine.currentIndexChanged.connect(self._on_engine_changed)
        self.cmb_quality.currentIndexChanged.connect(self._update_quality_hint)
        self.chk_bg.toggled.connect(self._invalidate_prepared)
        self.sld_ratio.valueChanged.connect(self._invalidate_prepared)

        # bas du panneau : l'action principale reste toujours visible
        foot = QFrame()
        foot.setObjectName("panelFooter")
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(20, 16, 20, 16)
        fv.setSpacing(10)
        self.btn_generate = make_button("Générer la 3D", kind="primary", icon="wand-sparkles", large=True,
                                        name="btn_generate")
        self.btn_generate.clicked.connect(self.on_generate)
        fv.addWidget(self.btn_generate)
        hint = QHBoxLayout()
        hint.setSpacing(4)
        hint.addStretch(1)
        hint.addWidget(KeyCap("Ctrl"))
        hint.addWidget(KeyCap("Entrée"))
        hint.addSpacing(4)
        hint.addWidget(text_label("pour générer", role="muted"))
        hint.addStretch(1)
        fv.addLayout(hint)
        pv.addWidget(foot)
        return panel

    def _build_right(self) -> QWidget:
        right = QWidget()
        right.setObjectName("transparent")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.viewport = ViewportFrame()
        self.viewer = self.viewport.viewer
        self.btn_reset, self.btn_wire, self.btn_spin = self.viewport.btn_reset, self.viewport.btn_wire, self.viewport.btn_spin
        self.btn_turn, self.btn_flip = self.viewport.btn_turn, self.viewport.btn_flip
        self.error_panel = self.viewport.error
        self.btn_reset.clicked.connect(self.viewer.reset_view)
        self.btn_wire.toggled.connect(self.viewer.set_wireframe)
        self.btn_spin.toggled.connect(self.viewer.set_auto_rotate)
        self.btn_turn.clicked.connect(lambda: self.on_rotate("turn"))
        self.btn_flip.clicked.connect(lambda: self.on_rotate("flip"))
        self.error_panel.retry.connect(self._on_retry)
        self.error_panel.back.connect(self._on_back)
        self.error_panel.copyDetails.connect(self._on_copy_details)
        self.error_panel.openLog.connect(self.on_open_log)
        rv.addWidget(self.viewport, 1)

        bar = QFrame()
        bar.setObjectName("exportBar")
        self._export_bar = bar
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(20, 12, 20, 12)
        bh.setSpacing(12)
        bh.addWidget(text_label("Format", role="label"))
        self.seg_format = Segmented(accessible_name="Format du fichier")
        self.seg_format.addItem("GLB : couleurs dans le fichier", "glb", label="GLB",
                                tooltip="Un seul fichier, avec les couleurs. Lisible partout.")
        self.seg_format.addItem("OBJ avec texture", "obj", label="OBJ + texture", tooltip=OBJ_TIP)
        self.seg_format.setMaximumWidth(theme.current().px(300))
        self.seg_format.currentIndexChanged.connect(self._on_format_changed)
        bh.addWidget(self.seg_format)
        bh.addStretch(1)
        self.btn_folder = IconButton("folder-open", "Afficher le dossier du fichier enregistré", name="btn_folder")
        self.btn_folder.clicked.connect(self.on_show_folder)
        self.btn_save = make_button("Enregistrer sous…", kind="primary", icon="save", name="btn_save")
        self.btn_save.clicked.connect(self.on_save)
        bh.addWidget(self.btn_folder)
        bh.addWidget(self.btn_save)
        rv.addWidget(bar)
        return right

    def _build_footer(self) -> QFrame:
        foot = QFrame()
        foot.setObjectName("footer")
        self._footer = foot
        h = QHBoxLayout(foot)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(16)
        self.status = ElidedLabel()
        self.status.setProperty("role", "secondary")
        self.progress = IndeterminateBar()
        self.progress.setFixedWidth(theme.current().px(160))
        self.progress.setVisible(False)
        privacy = text_label("Calcul local : tes images ne quittent pas cet ordinateur.", role="muted")
        h.addWidget(self.status, 1)
        h.addWidget(self.progress)
        h.addWidget(privacy)
        return foot

    def _apply_metrics(self) -> None:
        """Tailles qui dépendent de l'échelle du texte."""
        t = theme.current()
        self._topbar.setFixedHeight(t.px(60))
        self._footer.setFixedHeight(t.px(40))
        self._left.setFixedWidth(t.px(392))
        self.seg_format.setMaximumWidth(t.px(300))
        self.progress.setFixedWidth(t.px(160))
        self.setMinimumSize(t.px(1000), t.px(680))

    def _initial_size(self) -> None:
        """Grande fenêtre par défaut, sans dépasser 90 % de l'écran (portables compacts)."""
        t = theme.current()
        width, height = t.px(1280), t.px(840)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            width, height = min(width, int(area.width() * 0.9)), min(height, int(area.height() * 0.9))
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))

    def _bind_shortcuts(self) -> None:
        for keys, slot in (
            ("Ctrl+O", self.on_open),
            ("Ctrl+V", self.on_paste),
            ("Ctrl+S", self.on_save),
            ("Ctrl+Return", self.on_generate),
            ("Ctrl+Enter", self.on_generate),
            ("Ctrl+0", self.viewer.reset_view),
        ):
            QShortcut(QKeySequence(keys), self, activated=lambda slot=slot: self._if_studio(slot))
        QShortcut(QKeySequence("Esc"), self, activated=self._on_escape)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # le focus clavier n'est visible qu'à l'usage du clavier : au démarrage il repose sur le fond, pas sur un bouton
        if not self._gate_visible():
            self._root.setFocus(Qt.FocusReason.OtherFocusReason)

    # ---- réglages mémorisés -------------------------------------------------
    def _restore_settings(self) -> None:
        s = self.settings
        self.chk_bg.setChecked(s.value("remove_bg", True, type=bool))
        self.sld_ratio.setValue(s.value("ratio", 85, type=int))
        self._bake_pref = s.value("bake", False, type=bool)
        self._set_format_index(1 if self._bake_pref else 0)
        self.chk_color.setChecked(s.value("colorize", True, type=bool))
        self.spn_seed.setValue(s.value("seed", 42, type=int))
        self.cmb_engine.setCurrentIndex(min(max(s.value("engine", 0, type=int), 0), self.cmb_engine.count() - 1))
        self._on_engine_changed()  # remplit la liste des qualités du moteur choisi
        self.cmb_quality.setCurrentIndex(self._saved_quality(self._engine_id()))
        self._update_ratio_label()

    def _saved_quality(self, engine_id: str) -> int:
        if engine_id == "triposg":
            return min(max(self.settings.value("quality_sg", DEFAULT_QUALITY_INDEX_SG, type=int), 0), len(QUALITIES_SG) - 1)
        return min(max(self.settings.value("quality", DEFAULT_QUALITY_INDEX, type=int), 0), len(QUALITIES) - 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        s = self.settings
        s.setValue("remove_bg", self.chk_bg.isChecked())
        s.setValue("ratio", self.sld_ratio.value())
        s.setValue("engine", self.cmb_engine.currentIndex())
        s.setValue("quality_sg" if self._engine_id() == "triposg" else "quality", self.cmb_quality.currentIndex())
        s.setValue("bake", self._bake_pref)
        s.setValue("colorize", self.chk_color.isChecked())
        s.setValue("seed", self.spn_seed.value())
        s.setValue("theme", self.theme_pref)
        s.setValue("text_scale", self.text_scale)
        s.setValue("reduce_motion", self.reduce_motion)
        self.viewer.set_auto_rotate(False)
        super().closeEvent(event)

    # ---- apparence ----------------------------------------------------------
    def _open_menu(self) -> None:
        self.menu.set_state(self.theme_pref, self.text_scale, self.reduce_motion)
        self.menu.popup_below(self.btn_menu)

    def _reapply_theme(self) -> None:
        theme.apply_theme(QApplication.instance(), self.theme_pref, self.text_scale)
        self.viewer.apply_theme()
        self._refresh_ui()

    def _set_theme(self, mode: str) -> None:
        self.theme_pref = mode
        self.settings.setValue("theme", mode)
        self._reapply_theme()

    def _set_scale(self, scale: float) -> None:
        self.text_scale = scale
        self.settings.setValue("text_scale", scale)
        self._reapply_theme()

    def _set_reduce_motion(self, reduced: bool) -> None:
        self.reduce_motion = reduced
        self.settings.setValue("reduce_motion", reduced)
        Motion.refresh(reduced)
        self.progress.setActive(False)
        self.progress.setActive(self._task is not None)

    def _system_scheme_changed(self, *_args) -> None:
        if self.theme_pref == "system":
            self._reapply_theme()

    # ---- moteur -------------------------------------------------------------
    def _engine_id(self) -> str:
        return self.cmb_engine.currentData() or "triposr"

    def _qualities(self, engine_id: str):
        return QUALITIES_SG if engine_id == "triposg" else QUALITIES

    def _fill_quality(self, engine_id: str) -> None:
        self.cmb_quality.blockSignals(True)
        self.cmb_quality.clear()
        for label, value in self._qualities(engine_id):
            self.cmb_quality.addItem(label, value, label=label.split(" (")[0])
        default = DEFAULT_QUALITY_INDEX_SG if engine_id == "triposg" else DEFAULT_QUALITY_INDEX
        self.cmb_quality.setCurrentIndex(default)
        self.cmb_quality.blockSignals(False)
        self.lbl_quality.setText("Qualité (nombre d'étapes)" if engine_id == "triposg" else "Qualité du maillage")
        self._update_quality_hint()

    def _update_quality_hint(self, *_args) -> None:
        engine_id = self._engine_id()
        index = self.cmb_quality.currentIndex()
        if 0 <= index < len(self._qualities(engine_id)):
            self.lbl_quality_hint.setText(QUALITY_HINTS.get((engine_id, self._qualities(engine_id)[index][1]), ""))

    def _on_engine_changed(self, *_args) -> None:
        previous = getattr(self, "_filled_engine", None)
        engine_id = self._engine_id()
        if previous is not None and previous != engine_id:
            # on mémorise le réglage de l'ancien moteur avant de changer la liste
            key = "quality_sg" if previous == "triposg" else "quality"
            self.settings.setValue(key, self.cmb_quality.currentIndex())
        if previous != engine_id:
            self._fill_quality(engine_id)
            self.cmb_quality.setCurrentIndex(self._saved_quality(engine_id))
            self._filled_engine = engine_id
            self._invalidate_prepared()
        self._update_engine_widgets()

    def _active_engine(self) -> str:
        """Moteur du résultat affiché (c'est lui qui décide de l'export), sinon moteur choisi."""
        return self.result["engine"] if self.result is not None else self._engine_id()

    def _update_engine_widgets(self) -> None:
        triposg = self._active_engine() == "triposg"
        self.btn_turn.setVisible(triposg)
        self.btn_flip.setVisible(triposg)
        # TripoSG exporte ses couleurs dans le GLB : pas de texture cuite
        self.seg_format.setItemEnabled(
            1, not triposg, "Non disponible avec TripoSG : ses couleurs sont dans le fichier GLB." if triposg else OBJ_TIP
        )
        self._set_format_index(0 if triposg else (1 if self._bake_pref else 0))
        selected_sg = self._engine_id() == "triposg"  # réglages de génération : suivent le moteur choisi
        self.chk_color.setVisible(selected_sg)
        self.seed_row.setVisible(selected_sg)
        self.viewport._layout_overlays()

    def _set_format_index(self, index: int) -> None:
        self._syncing_format = True
        self.seg_format.setCurrentIndex(index)
        self._syncing_format = False

    def _on_format_changed(self, index: int) -> None:
        if not self._syncing_format:
            self._bake_pref = index == 1

    def options(self) -> Options:
        engine_id = self._engine_id()
        return Options(
            remove_bg=self.chk_bg.isChecked(),
            ratio=self.sld_ratio.value() / 100.0,
            resolution=self._qualities(engine_id)[self.cmb_quality.currentIndex()][1],
            engine=engine_id,
            colorize=self.chk_color.isChecked(),
            seed=self.spn_seed.value(),
        )

    def _update_ratio_label(self) -> None:
        self.lbl_ratio.setText(f"{self.sld_ratio.value()} %")
        self.sld_ratio.setAccessibleDescription(f"{self.sld_ratio.value()} pour cent")

    def _invalidate_prepared(self, *_args) -> None:
        """Les réglages de détourage ont changé : l'aperçu « Détourée » n'est plus celui que le modèle recevrait."""
        if hasattr(self, "drop") and self.drop.has_prepared():
            self.drop.set_prepared(None)

    # ---- état ---------------------------------------------------------------
    def set_status(self, text: str) -> None:
        self.status.setText(text)  # ElidedLabel : texte complet dans l'info-bulle
        self.viewport.busy.set_status(text)

    @property
    def busy(self) -> bool:
        return self._task is not None

    def set_busy(self, busy: bool) -> None:
        """Compatibilité : l'état occupé vient de la tâche en cours ; on rafraîchit simplement l'interface."""
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        """Dérive tout l'affichage de l'état (tâche, résultat, erreur) : une seule action principale par vue."""
        busy = self._task is not None
        has_result = self.result is not None
        error = self._error is not None

        self.drop.setControlsEnabled(not busy)
        self.btn_generate.setEnabled(not busy)
        self.btn_save.setEnabled(not busy and has_result)
        self.btn_folder.setEnabled(not busy and self.last_saved is not None)
        self.seg_format.setEnabled(not busy and has_result)
        for w in (self.btn_turn, self.btn_flip):
            w.setEnabled(not busy and has_result)
        self.progress.setVisible(busy)
        self.progress.setActive(busy)

        self.btn_generate.setText("Générer à nouveau" if has_result else "Générer la 3D")
        set_kind(self.btn_generate, "primary" if (not has_result and not error) else None)
        set_kind(self.btn_save, "primary" if (has_result and not error) else None)

        if self._task_kind == "generate" and busy:
            page = ViewportFrame.BUSY
        elif error:
            page = ViewportFrame.ERROR
        elif has_result:
            page = ViewportFrame.RESULT
        else:
            page = ViewportFrame.EMPTY
        if page != self.viewport.page_name():
            self.viewport.show_page(page)

    # ---- chargement d'image -------------------------------------------------
    def toast(self, text: str, kind: str = "success", timeout: int = TOAST_SECONDS) -> None:
        self.viewport.toast.show_message(text, kind, timeout)

    def load_path(self, path: str) -> None:
        try:
            image = Image.open(path)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((2048, 2048))
            image = image.convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            self.toast(f"Impossible d'ouvrir cette image ({type(exc).__name__}). Choisis un fichier PNG, JPG ou WebP.",
                       "error", 8000)
            self.set_status(f"Image illisible : {exc}")
            return
        self.input_name = Path(path).stem or "modele"
        self.set_input(image)
        self.settings.setValue("last_image_dir", str(Path(path).parent))

    def set_input(self, image: Image.Image) -> None:
        self.input_image = image
        self.drop.set_image(image)
        # une nouvelle image rend l'ancien modèle caduc : on repart d'un état propre
        self.result = None
        self._error = None
        self.viewer.clear()
        self.viewport.info.setText("")
        self._update_engine_widgets()
        self._refresh_ui()
        self.set_status(f"Image chargée ({image.width} × {image.height}). Clique sur « Générer la 3D ».")

    def on_open(self) -> None:
        if self._task is not None:
            return
        start = self.settings.value("last_image_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une image", start, IMAGE_FILTER)
        if path:
            self.load_path(path)

    def on_paste(self) -> None:
        if self._task is not None:
            return
        data = QGuiApplication.clipboard().mimeData()
        if data.hasUrls():
            for url in data.urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS:
                    self.load_path(url.toLocalFile())
                    return
        if data.hasImage():
            qimage = QGuiApplication.clipboard().image()
            if not qimage.isNull():
                self.input_name = "image_collee"
                self.set_input(qimage_to_pil(qimage))
                return
        self.set_status("Le presse-papiers ne contient pas d'image.")
        self.toast("Le presse-papiers ne contient pas d'image. Copie une image, puis réessaie.", "warning")

    @staticmethod
    def _first_image_url(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS:
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._first_image_url(event) and not self._gate_visible():
            event.acceptProposedAction()
            self.drop.set_dragging(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.set_dragging(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop.set_dragging(False)
        path = self._first_image_url(event)
        if path and self._task is None and not self._gate_visible():
            self.load_path(path)
            event.acceptProposedAction()

    # ---- tâches -------------------------------------------------------------
    def run_task(self, fn, on_done, on_partial=None, kind: str = "generate", retry=None) -> None:
        if self._task is not None:
            return
        try:
            licensing.require()
        except LicenseError:
            self._check_license()  # affiche l'écran Licence
            return
        task = Task(fn)
        task.signals.progress.connect(self.set_status)
        task.signals.partial.connect(self._task_partial)
        task.signals.finished.connect(self._task_finished)
        task.signals.failed.connect(self._task_failed)
        self._task, self._on_done, self._on_partial = task, on_done, on_partial
        self._task_kind, self._retry, self._error = kind, retry, None
        self.viewport.toast.hide_now()
        titles = {"generate": "Génération en cours", "preview": "Détourage en cours", "save": "Export en cours"}
        self.viewport.busy.title.setText(titles.get(kind, "Travail en cours"))
        self._refresh_ui()
        self.pool.start(task)

    def _task_partial(self, value) -> None:
        if self._on_partial is not None:
            self._on_partial(value)

    def _task_finished(self, result) -> None:
        callback = self._on_done
        self._task = self._on_done = self._on_partial = None
        self._refresh_ui()
        if callback is not None:
            callback(result)
        self._task_kind = None

    def _task_failed(self, message: str, details: str) -> None:
        kind = self._task_kind or "generate"
        self._task = self._on_done = self._on_partial = None
        self._task_kind = None
        if details == LICENSE_FAILURE:  # la licence a pris fin : écran Licence, pas un panneau d'erreur
            self._refresh_ui()
            self._check_license()
            return
        if kind == "preview":
            self.drop.set_prepared(None)
        self._error = {"kind": kind, "message": message, "details": details}
        self.error_panel.set_error(
            FAILURE_TITLES.get(kind, "L'opération a échoué"),
            message,
            FAILURE_HINT,
            f"{message}\n\nJournal : {LOG_FILE}\n\n{details}",
            can_go_back=self.result is not None,
            retry_label="Réessayer",
        )
        self.viewport.toast.hide_now()
        self.set_status(f"Échec : {message.splitlines()[0] if message else 'erreur inconnue'}")
        self._refresh_ui()
        self.error_panel.btn_retry.setFocus(Qt.FocusReason.TabFocusReason)  # le clavier arrive sur l'action utile

    def _on_retry(self) -> None:
        retry = self._retry
        self._error = None
        self._refresh_ui()
        if retry is not None:
            retry()

    def _on_back(self) -> None:
        self._error = None
        self._refresh_ui()
        self.set_status("Modèle d'origine conservé.")

    def _on_copy_details(self) -> None:
        QGuiApplication.clipboard().setText(self.error_panel.details)
        self.toast("Détails copiés. Colle-les dans un message pour obtenir de l'aide.", "success")

    def on_open_log(self) -> None:
        if LOG_FILE.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))
        else:
            self.toast("Le journal n'existe pas encore : il est créé au premier lancement d'un calcul.", "warning")

    def on_open_licences(self) -> None:
        for candidate in (paths.APP_ROOT / "licenses" / "THIRD_PARTY_NOTICES.md", paths.APP_ROOT / "THIRD_PARTY_NOTICES.md"):
            if candidate.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                return
        self.toast("Le fichier des licences est introuvable dans cette installation.", "warning")

    # ---- licence ------------------------------------------------------------
    def _gate_visible(self) -> bool:
        return self.stack.currentWidget() is self.gate

    def _if_studio(self, slot) -> None:
        if not self._gate_visible():
            slot()

    def _on_escape(self) -> None:
        if self._gate_visible():
            if self._gate_closable:
                self._close_gate()
        else:
            self.viewport.toast.dismiss()

    def _check_license(self) -> licensing.LicenseStatus:
        """Relit l'état de la licence (rapide, hors ligne) ; ferme l'étude derrière l'écran Licence si elle n'est plus valable."""
        status = licensing.get_manager().status()
        self._license_status = status
        self.chip_trial.set_status(status)
        if not status.allowed:
            if not self._gate_visible() or self._gate_closable:
                self._show_gate(status, closable=False)
        elif self._gate_visible() and not self._gate_closable:
            self._close_gate()
        return status

    def _show_gate(self, status: licensing.LicenseStatus, closable: bool) -> None:
        self._gate_closable = closable
        self.gate.show_status(status, closable)
        self.stack.setCurrentWidget(self.gate)
        self.viewport.toast.hide_now()
        self.gate.focus_first()

    def _close_gate(self) -> None:
        if not licensing.get_manager().status().allowed:
            return
        self._gate_closable = False
        self.stack.setCurrentWidget(self._root)
        self._root.setFocus(Qt.FocusReason.OtherFocusReason)

    def on_open_license(self) -> None:
        status = licensing.get_manager().status()
        self._license_status = status
        self._show_gate(status, closable=status.allowed)

    def _license_changed(self, status) -> None:
        self._license_status = status
        self.chip_trial.set_status(status)
        if status.allowed:
            self._close_gate()
            if status.state == "licensed":
                self.toast("Licence activée. Merci, et bonne création !", "success")
            else:
                self.toast(f"Essai gratuit de {TRIAL_DAYS} jours démarré. Tout est débloqué.", "success")
        else:
            self._show_gate(status, closable=False)

    # ---- actions ------------------------------------------------------------
    def _require_image(self) -> bool:
        if self.input_image is None:
            self.set_status("Dépose d'abord une image (glisser-déposer, Ctrl+O ou Ctrl+V).")
            self.toast("Dépose d'abord une image : glisse-la dans la fenêtre, Ctrl+O pour choisir, Ctrl+V pour coller.",
                       "warning")
            return False
        return True

    def show_prepared(self, image: Image.Image) -> None:
        self.drop.set_prepared(image)

    def _on_view_changed(self, index: int) -> None:
        """La bascule « Détourée » demande l'aperçu s'il n'a pas encore été calculé."""
        if index == 1 and not self.drop.has_prepared() and self._task is None and self.input_image is not None:
            self.on_preview()

    def on_preview(self) -> None:
        if not self._require_image():
            return
        opts, image, engine = self.options(), self.input_image, self.engine

        def job(progress, partial):
            if opts.engine == "triposg":
                return engine.prepare_triposg(image, opts.remove_bg, opts.ratio, progress)[0]
            return engine.preprocess(image, opts.remove_bg, opts.ratio, progress)

        def done(prepared):
            self.show_prepared(prepared)
            self.set_status("Aperçu prêt. Si le détourage est mauvais, essaie une autre image ou désactive-le.")

        self.run_task(job, done, kind="preview", retry=self.on_preview)

    def on_generate(self) -> None:
        if self._task is not None:
            return
        if not self._require_image():
            return
        opts, image, engine = self.options(), self.input_image, self.engine
        if opts.engine == "triposg" and not engine.triposg_ready():
            self.toast(INSTALL_HINT, "warning", 9000)
            return

        def job(progress, partial):
            if opts.engine == "triposg":
                prepared, cut = engine.prepare_triposg(image, opts.remove_bg, opts.ratio, progress)
                partial(prepared)
                preview, full, notes = engine.generate_triposg(
                    prepared, opts.resolution, progress, seed=opts.seed, cutout=cut if opts.colorize else None
                )
                return {"engine": "triposg", "prepared": prepared, "mesh": preview, "mesh_export": full,
                        "scene_codes": None, "extra": IDENTITY.copy(), "notes": notes}
            prepared = engine.preprocess(image, opts.remove_bg, opts.ratio, progress)
            partial(prepared)
            progress("Génération du modèle 3D…")
            mesh, scene_codes = engine.generate(prepared, opts.resolution, progress)
            return {"engine": "triposr", "prepared": prepared, "mesh": mesh, "mesh_export": None,
                    "scene_codes": scene_codes, "extra": IDENTITY.copy(), "notes": []}

        self.run_task(job, self._generated, on_partial=self.show_prepared, kind="generate", retry=self.on_generate)

    @staticmethod
    def _orientation(result: dict):
        """Rotation qui amène le maillage affiché dans le repère de l'export."""
        return ORIENTATION if result["engine"] == "triposr" else result["extra"]

    def _generated(self, result: dict) -> None:
        self.result = result
        self._error = None
        self.show_prepared(result["prepared"])
        mesh = result["mesh"]
        self.viewer.set_mesh(mesh, orientation=self._orientation(result))
        self._update_engine_widgets()
        self._refresh_ui()  # réactive Enregistrer et les boutons de rotation
        full = result["mesh_export"] if result["mesh_export"] is not None else mesh
        count = f"{len(full.vertices):,}".replace(",", " ")
        engine_name = "TripoSG" if result["engine"] == "triposg" else "TripoSR"
        self.viewport.info.setText(f"{count} sommets · {engine_name}")
        self.viewport._layout_overlays()
        extra = (
            " Si l'objet apparaît couché ou de côté, utilise « Redresser » ou « Pivoter 90° »."
            if result["engine"] == "triposg" else ""
        )
        notes = " ".join(result.get("notes") or [])
        ready = f"Modèle prêt ({count} sommets). Tourne-le à la souris, puis « Enregistrer sous… ».{extra}"
        # les remarques d'abord : la ligne d'état est coupée à droite quand elle est trop longue
        self.set_status(f"{notes}  {ready}".strip())

    def on_rotate(self, kind: str) -> None:
        if self.result is None or self._task is not None or self.result["engine"] != "triposg":
            return
        step = rotation("y", 90) if kind == "turn" else rotation("x", -90)
        self.result["extra"] = step @ self.result["extra"]
        self.viewer.set_mesh(self.result["mesh"], orientation=self._orientation(self.result))

    def on_save(self) -> None:
        if self.result is None or self._task is not None:
            return
        bake = self.seg_format.currentIndex() == 1 and self.result["engine"] == "triposr"
        folder = self.settings.value("last_save_dir", str(Path.home()))
        suffix = ".obj" if bake else ".glb"
        filters = (
            "Modèle OBJ (*.obj);;Modèle GLB (*.glb)" if bake else "Modèle GLB (*.glb);;Modèle OBJ (*.obj)"
        )
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le modèle 3D", str(Path(folder) / f"{self.input_name}{suffix}"), filters
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() not in (".glb", ".obj"):
            path = path.with_suffix(suffix)
        self.settings.setValue("last_save_dir", str(path.parent))
        result, engine = self.result, self.engine

        def job(progress, partial):
            if result["engine"] == "triposg":
                return engine.export_triposg(result, path, progress)
            return engine.export(result["mesh"], result["scene_codes"], path, bake, progress)

        self.run_task(job, lambda p: self._saved(p, bake), kind="save", retry=self.on_save)

    def _saved(self, path, baked: bool = False) -> None:
        self.last_saved = Path(path)
        self._refresh_ui()
        extra = " (avec son image de texture)" if self.last_saved.suffix.lower() == ".obj" and baked else ""
        self.set_status(f"Enregistré : {self.last_saved}{extra}")
        self.toast(f"Enregistré : {self.last_saved.name}{extra}", "success")

    def on_show_folder(self) -> None:
        if self.last_saved is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_saved.parent)))


# =============================================================================
#  Démarrage
# =============================================================================
def main(engine=None) -> int:
    paths.ensure_user_dirs()
    logging.basicConfig(
        filename=str(LOG_FILE),
        filemode="w",
        format="%(asctime)s  %(levelname)s  %(message)s",
        level=logging.INFO,
        encoding="utf-8",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Image vers 3D")
    settings = QSettings("ImageVers3D", "Studio")
    Motion.refresh(settings.value("reduce_motion", False, type=bool))
    theme.apply_theme(app, settings.value("theme", "dark", type=str), settings.value("text_scale", 1.0, type=float))

    def excepthook(exc_type, exc, tb):
        log.error("Erreur non gérée :\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, "Erreur inattendue", f"{exc}\n\nDétails techniques : {LOG_FILE}")

    sys.excepthook = excepthook

    if engine is None:
        if torch is None:
            QMessageBox.critical(
                None,
                "PyTorch introuvable",
                "L'installation est incomplète.\nLance « Réparer l'installation » depuis le menu Démarrer "
                "(dossier « Image vers 3D »), ou réinstalle l'application.",
            )
            return 1
        engine = Engine()

    window = MainWindow(engine, settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
