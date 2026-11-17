#!/usr/bin/env python3
"""
studio.py - « ThreeRex » : application de bureau, 100 % locale.

Glisse une image dans la fenêtre, clique sur « Générer la 3D », tourne le
modèle à la souris, puis enregistre-le en .glb, en .obj ou en .stl (prêt pour l'impression 3D).

L'apparence est définie dans theme.py (couleurs), fx.py (effets, mascotte), widgets.py, viewport.py et pages.py ; voir docs/DESIGN.md.

Lancement :  python -m threerex   (ou le raccourci « ThreeRex » du menu Démarrer)
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

import gc
import logging
import time
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
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSettings, QThreadPool, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QShortcut,
)
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
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__, fx, icons, paths, printing, theme
from .creations import CreationStore
from .geometry import IDENTITY, ORIENTATION, rotation
from .image_checks import IMAGE_PROMPT, check_image
from .mesh_tools import prepare_for_export
from .pages import CreationsPage, SettingsPage
from .print_dialog import PrintDialog
from .printing import PrintOptions
from .theme import Motion
from .triposg_runner import INSTALL_HINT, TripoSGRunner
from .trellis_runner import NOT_INSTALLED, PRESETS as TRELLIS_PRESETS, QUANTS, TrellisRunner, cancel_all as cancel_trellis, export_glb, human_size
from .viewport import MeshViewer, ViewportFrame  # noqa: F401 - MeshViewer et ViewportFrame restent importables depuis ici
from .widgets import (
    DropZone,
    ElidedLabel,
    HardwareChip,
    IconButton,
    IndeterminateBar,
    KeyCap,
    Segmented,
    make_button,
    qimage_to_pil,
    set_kind,
    set_prop,
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
    ("trellis", "TRELLIS.2 : qualité maximale, textures PBR"),
    ("triposg", "TripoSG : forme fine, couleurs de ton image"),
]
QUALITIES_SG = [("Rapide (25 étapes)", 25), ("Standard (50 étapes)", 50), ("Soigné (80 étapes)", 80)]
DEFAULT_QUALITY_INDEX_SG = 1
FMT_GLB, FMT_OBJ, FMT_STL = 0, 1, 2  # indices du sélecteur « Format » de la barre d'export
STL_TIP = ("Pour l'impression 3D : surface réparée et fermée, mise à l'échelle en millimètres, posée à plat. "
           "Sans couleurs : un STL n'en contient pas.")
STL_OPEN_HINT = "Surface non fermée : ouvre le STL dans PrusaSlicer ou Meshmixer."  # bulle du robot (deux lignes au plus)
QUALITIES_TRELLIS = [(preset.label, key) for key, preset in TRELLIS_PRESETS.items()]
DEFAULT_QUALITY_INDEX_TRELLIS = 1  # « Détaillé (1024) »
# Par moteur : qualités proposées, indice par défaut, clé du réglage mémorisé, intitulé du sélecteur.
ENGINE_QUALITY = {
    "triposr": (QUALITIES, DEFAULT_QUALITY_INDEX, "quality", "Qualité du maillage"),
    "triposg": (QUALITIES_SG, DEFAULT_QUALITY_INDEX_SG, "quality_sg", "Qualité (nombre d'étapes)"),
    "trellis": (QUALITIES_TRELLIS, DEFAULT_QUALITY_INDEX_TRELLIS, "quality_trellis", "Qualité (finesse du modèle)"),
}

log = logging.getLogger("studio")


def enable_dark_titlebar(window) -> None:
    """Barre de titre sombre sous Windows 10/11 (attribut DWM 20) ; sans effet ailleurs ou si Windows refuse."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001 - purement décoratif
        log.debug("Barre de titre sombre indisponible", exc_info=True)


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
        self.trellis = TrellisRunner()

    def triposg_ready(self) -> bool:
        return self.triposg.available()

    # ---- TRELLIS.2 (moteur « Qualité maximale », programme séparé, voir trellis_runner.py) ----
    def trellis_supported(self) -> bool:
        return self.trellis.supported()

    def trellis_ready(self) -> bool:
        return self.trellis.ready()

    def trellis_download_size(self) -> int:
        return self.trellis.download_size()

    def install_trellis(self, progress) -> None:
        self.trellis.install(progress)

    def trellis_quant(self) -> str:
        return self.trellis.quant

    def set_trellis_quant(self, quant: str) -> None:
        self.trellis.set_quant(quant)

    def _release_gpu(self) -> None:
        """TripoSR garde ses poids (~1,5 Go) dans la mémoire de la carte : on les libère avant de lancer TRELLIS.2, qui en
        a besoin de presque toute (carte de 12 Go). TripoSR se recharge tout seul au prochain usage."""
        self.model = None
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def prepare_trellis(self, image: Image.Image, remove_bg: bool, ratio: float, progress) -> Image.Image:
        """Aperçu du détourage tel que TRELLIS.2 le fait (BiRefNet) ; à défaut, le détourage de TripoSR. Sur fond blanc."""
        self._release_gpu()
        progress("Détourage de l'image (BiRefNet)…")
        cut = self.trellis.cutout(image, remove_bg, progress)
        if cut is None:
            return self.prepare_triposg(image, remove_bg, ratio, progress)[0]
        white = Image.new("RGB", cut.size, (255, 255, 255))
        white.paste(cut, mask=cut.getchannel("A"))
        return white

    def generate_trellis(self, image: Image.Image, quality: str, remove_bg: bool, seed: int, progress,
                         texture: str = "standard") -> dict:
        """{"glb": octets du .glb, "mesh": maillage d'aperçu, "notes": [...], "res": résolution, "fine": texture fine}."""
        self._release_gpu()
        return self.trellis.generate(image, quality, remove_bg, seed, progress, texture)

    def export_trellis(self, result: dict, path: Path, progress) -> Path:
        progress("Export du fichier…")
        return export_glb(result["glb"], path, result["extra"])

    def export_print(self, result: dict, path: Path, options: PrintOptions, progress):
        """STL prêt à imprimer, quel que soit le moteur. Renvoie (chemin, rapport de réparation)."""
        progress("Préparation pour l'impression : réparation du maillage…")
        report = printing.export_stl(printing.source_mesh(result), path, options.height_mm, options.flatten)
        return path, report

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
        session = self._rembg_session(remove_bg, progress)
        progress("Détourage de l'image…" if remove_bg else "Préparation de l'image…")
        return self._module().preprocess(image, remove_bg, ratio, session)

    def prepare_triposg(self, image: Image.Image, remove_bg: bool, ratio: float, progress):
        """TripoSG : renvoie (objet centré sur fond blanc, objet détouré en RGBA pour les couleurs)."""
        session = self._rembg_session(remove_bg, progress)
        progress("Détourage de l'image…" if remove_bg else "Préparation de l'image…")
        cut = self._module().cutout(image, remove_bg, ratio, session)
        white = Image.new("RGB", cut.size, (255, 255, 255))
        white.paste(cut, mask=cut.getchannel("A"))
        return white, cut

    def generate(self, prepared: Image.Image, resolution: int, progress):
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
        return self.triposg.generate(prepared, steps, progress, seed=seed, cutout=cutout)

    def export_triposg(self, result: dict, path: Path, progress) -> Path:
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
        progress("Export du fichier (la texture peut prendre quelques secondes)…" if bake else "Export du fichier…")
        # L'export applique une rotation sur place : on travaille sur une copie
        # pour pouvoir exporter plusieurs fois le même résultat.
        return self._module().export_mesh(self.model, mesh.copy(), scene_codes, path, bake)


# =============================================================================
#  Tâches en arrière-plan
# =============================================================================
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
#  Fenêtre principale
# =============================================================================
@dataclass
class Options:
    remove_bg: bool
    ratio: float
    resolution: int | str  # TripoSR : finesse du maillage ; TripoSG : nombre d'étapes ; TRELLIS.2 : « rapide », « detaille »…
    engine: str = "triposr"
    colorize: bool = True  # TripoSG : colorier la forme d'après l'image
    seed: int = 42  # TripoSG et TRELLIS.2 : numéro de variante
    texture: str = "standard"  # TRELLIS.2 : « standard » ou « fine » (atlas 4096, décodage PBR 1024)
    variants: int = 1  # TRELLIS.2 : nombre de variantes générées à la suite (numéros seed, seed+1…)


# Explication courte sous le sélecteur de qualité : ce que le réglage change.
QUALITY_HINTS = {
    ("triposr", 128): "Maillage 128 : le plus rapide, détails simplifiés.",
    ("triposr", 192): "Maillage 192 : rapide, détails corrects.",
    ("triposr", 256): "Maillage 256 : recommandé, bon équilibre vitesse et détail.",
    ("triposr", 320): "Maillage 320 : le plus fin, plus lent, plus de mémoire GPU.",
    ("triposg", 25): "25 étapes : brouillon rapide.",
    ("triposg", 50): "50 étapes : recommandé.",
    ("triposg", 80): "80 étapes : le plus soigné, le plus lent.",
    ("trellis", "rapide"): "512 : le plus rapide, détails simplifiés.",
    ("trellis", "detaille"): "1024 : recommandé, beaucoup de détails ; compte quelques minutes.",
    ("trellis", "maximum"): "1024 avec plus d'étapes : le plus soigné, environ deux fois plus long.",
    ("trellis", "ultra"): "1536 : expérimental, le plus fin mais très long et très gourmand ; si la carte manque de mémoire, "
                          "le calcul est refait en 1024 puis en 512.",
}
FAILURE_TITLES = {
    "generate": "La génération a échoué",
    "preview": "Le détourage a échoué",
    "save": "L'enregistrement a échoué",
    "install": "L'installation du moteur a échoué",
}
FAILURE_HINT = "Réessaie. Si le problème continue, copie les détails et ouvre le journal : ils expliquent ce qui s'est passé."
TOAST_SECONDS = 5000
OBJ_TIP = "OBJ avec texture : crée une vraie image de texture. Plus propre dans Blender, mais l'export est plus long."
ENGINE_NAMES = {"triposr": "TripoSR", "trellis": "TRELLIS.2", "triposg": "TripoSG"}
# Pastille à côté du choix du moteur : ce que chacun apporte (jamais une promesse de vitesse chiffrée)
ENGINE_BADGES = {"trellis": ("Recommandé", "orange"), "triposr": ("Rapide", "violet"), "triposg": ("Expérimental", "violet")}
# Astuces du robot (un clic sur lui passe à la suivante) : de vrais conseils, ceux de docs/IMAGE_DE_DEPART.md et de la qualité
TIPS = (
    "Un seul objet, bien centré et bien éclairé : c'est ce que l'IA reconstruit le mieux.",
    "Évite les reflets, les objets transparents et les ombres très dures.",
    "L'IA invente le dos de l'objet : essaie plusieurs variantes, garde la meilleure.",
    "Qualité maximale : compte plusieurs minutes par variante.",
    "Objet couché ? Utilise le bouton « Redresser » sous le visualiseur.",
    "Ctrl+V colle une image copiée ; tu peux aussi la glisser dans la fenêtre.",
)
LEFT_PANEL_WIDTH = (340, 392, 560)  # mini, défaut, maxi (pixels du thème)
TAB_STUDIO, TAB_CREATIONS, TAB_SETTINGS = 0, 1, 2


def format_duration(seconds: float) -> str:
    """« 42 s », « 2 min 14 s », « 1 h 05 min » : durée lisible."""
    total = max(int(round(seconds)), 0)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


class TopBar(QFrame):
    """Barre du haut : logo, onglets, état du calcul. Un filet dégradé violet la sépare du contenu."""

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        line = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        line.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.0))
        line.setColorAt(0.25, fx.with_alpha(t.color("violet"), 0.75))
        line.setColorAt(0.8, fx.with_alpha(t.color("accent"), 0.55))
        line.setColorAt(1.0, fx.with_alpha(t.color("accent"), 0.0))
        p.fillRect(QRectF(0, self.height() - 1.5, self.width(), 1.5), QBrush(line))


class MainWindow(QMainWindow):
    def __init__(self, engine, settings: QSettings | None = None, creations: CreationStore | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings if settings is not None else QSettings("ThreeRex", "Studio")
        self.store = creations if creations is not None else CreationStore()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self.input_image: Image.Image | None = None
        self.input_name = "modele"
        self.result: dict | None = None  # variante affichée (un des éléments de self.variants)
        self.variants: list[dict] = []
        self._problems: list[str] = []
        self._syncing_variant = False
        self.last_saved: Path | None = None
        self._task: Task | None = None
        self._task_kind: str | None = None
        self._on_done = None
        self._on_partial = None
        self._error: dict | None = None
        self._retry = None
        self._format_pref = FMT_GLB  # dernier format choisi (survit aux changements de moteur et aux nouveaux résultats)
        self._print = PrintOptions()  # derniers réglages d'impression 3D
        self._syncing_format = False
        self._gen_started: float | None = None
        self._last_duration: float | None = None
        self._tip_index = 0
        self._tip_override = ""
        self._fullscreen = False
        self._was_maximized = False
        self._left_base = LEFT_PANEL_WIDTH[1]  # largeur du panneau de gauche, en pixels du thème à 100 %
        self._sized_once = False

        scale = self.settings.value("text_scale", 1.0, type=float)
        self.text_scale = scale if scale in theme.TEXT_SCALES else 1.0
        self.reduce_motion = self.settings.value("reduce_motion", False, type=bool)
        self.effects = self.settings.value("effects", True, type=bool)
        Motion.refresh(self.reduce_motion, not self.effects)
        theme.apply_theme(QApplication.instance(), "dark", self.text_scale)

        self.setWindowTitle(APP_NAME if __version__.endswith("+dev") else f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        icon_path = paths.ASSETS_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self._apply_metrics()
        self._initial_size()
        self._fit_topbar()
        self._restore_settings()
        self._bind_shortcuts()
        self.viewer.apply_theme()
        theme.bus.changed.connect(self._apply_metrics)
        self._refresh_ui()
        self.set_status("Prêt. Dépose une image dans la fenêtre pour commencer.")

    # ---- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        root = fx.Backdrop()
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)

        outer.addWidget(self._build_topbar())
        self.pages = QStackedWidget()
        self.pages.setObjectName("transparent")
        self.pages.addWidget(self._build_studio_page())
        self.creations_page = CreationsPage(self.store)
        self.creations_page.openRequested.connect(self.on_open_creation)
        self.creations_page.folderRequested.connect(self.on_show_creation_folder)
        self.pages.addWidget(self.creations_page)
        version = "version de développement" if __version__.endswith("+dev") else f"version {__version__}"
        self.settings_page = SettingsPage(version)
        self.settings_page.scaleChanged.connect(self._set_scale)
        self.settings_page.reduceMotionChanged.connect(self._set_reduce_motion)
        self.settings_page.effectsChanged.connect(self._set_effects)
        self.settings_page.openLogRequested.connect(self.on_open_log)
        self.settings_page.openLicencesRequested.connect(self.on_open_licences)
        self.settings_page.openDataRequested.connect(self.on_open_data_folder)
        self.settings_page.copyPromptRequested.connect(self.on_copy_prompt)
        self.settings_page.set_device(self.engine.device_label())
        self.pages.addWidget(self.settings_page)
        outer.addWidget(self.pages, 1)
        outer.addWidget(self._build_footer())

    def _build_topbar(self) -> QFrame:
        bar = TopBar()
        bar.setObjectName("topbar")
        self._topbar = bar
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 0, 20, 2)
        h.setSpacing(28)
        self.logo = fx.Logo(44)
        h.addWidget(self.logo)
        self.tabs = fx.TabBar()
        self.tabs.addTab("Image vers 3D", "box")
        self.tabs.addTab("Mes créations", "images")
        self.tabs.addTab("Paramètres", "settings")
        self.tabs.currentChanged.connect(self._on_tab)
        h.addWidget(self.tabs)
        h.addStretch(1)
        self.chip = HardwareChip()
        self.chip.set_device(self.engine.device_label())
        h.addWidget(self.chip)
        return bar

    def _build_studio_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("transparent")
        h = QHBoxLayout(page)
        h.setContentsMargins(16, 6, 16, 6)
        self.splitter = fx.GripSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        h.addWidget(self.splitter)
        return page

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
        lv.setContentsMargins(4, 4, 6, 4)
        lv.setSpacing(14)
        scroll.setWidget(body)
        pv.addWidget(scroll, 1)

        # --- importer l'image
        self.import_panel = fx.Panel("violet")
        iv = self.import_panel.vbox(8)
        iv.addWidget(fx.PanelHeader("Importer ton image"))
        self.drop = DropZone()
        self.drop.openRequested.connect(self.on_open)
        self.drop.pasteRequested.connect(self.on_paste)
        self.drop.viewChanged.connect(self._on_view_changed)
        self.btn_open, self.btn_paste = self.drop.btn_open, self.drop.btn_paste
        iv.addWidget(self.drop, 1)
        lv.addWidget(self.import_panel)

        # --- réglages avancés
        self.settings_panel = fx.CollapsiblePanel("Réglages avancés", "violet", expanded=True)
        sv = self.settings_panel.content
        sv.setSpacing(12)

        # moteur : seulement si TripoSG est déjà installé (il n'est pas distribué avec le logiciel)
        self.engine_row = QWidget()
        self.engine_row.setObjectName("transparent")
        ev = QVBoxLayout(self.engine_row)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(text_label("Moteur d'IA", role="label"))
        head.addStretch(1)
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        head.addWidget(self.badge)
        ev.addLayout(head)
        self.cmb_engine = QComboBox()
        self.cmb_engine.setAccessibleName("Moteur d'IA")
        for engine_id, label in ENGINES:
            if engine_id == "triposg" and not self.engine.triposg_ready():
                continue  # moteur non fourni : on ne le propose pas
            if engine_id == "trellis" and not self.engine.trellis_supported():
                continue  # programme Windows pour carte NVIDIA
            self.cmb_engine.addItem(label, engine_id)
        tooltip = "TripoSR : rapide, couleurs estimées par l'IA, forme approximative."
        if self.cmb_engine.findData("trellis") >= 0:
            tooltip += "\nTRELLIS.2 : le plus détaillé, avec de vraies textures (couleur, métal, rugosité). Plus lent."
        if self.cmb_engine.findData("triposg") >= 0:
            tooltip += "\nTripoSG (expérimental) : forme beaucoup plus fine, colorée d'après ton image."
        self.cmb_engine.setToolTip(tooltip)
        self.cmb_engine.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_engine.setMinimumContentsLength(10)
        ev.addWidget(self.cmb_engine)
        self.precision_row = QWidget()
        self.precision_row.setObjectName("transparent")
        pr = QVBoxLayout(self.precision_row)
        pr.setContentsMargins(0, 4, 0, 0)
        pr.setSpacing(6)
        pr.addWidget(text_label("Précision du modèle d'IA", role="label"))
        self.cmb_precision = QComboBox()
        self.cmb_precision.setAccessibleName("Précision du modèle d'IA")
        self.cmb_precision.addItem("Standard (6,5 Go)", "q4")
        self.cmb_precision.addItem("Haute (10 Go, plus de mémoire vidéo)", "q8")
        self.cmb_precision.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_precision.setMinimumContentsLength(10)
        self.cmb_precision.setToolTip(
            "Standard (q4) : modèles compressés, prévus pour les cartes de 12 Go.\n"
            "Haute (q8) : moins de compression, texture plus propre. À essayer quand le mode Détaillé passe sans repli ; "
            "demande un téléchargement de plus (environ 10 Go)."
        )
        self.cmb_precision.currentIndexChanged.connect(self._on_precision_changed)
        pr.addWidget(self.cmb_precision)
        ev.addWidget(self.precision_row)
        self.lbl_engine_note = text_label("", role="muted", wrap=True)
        ev.addWidget(self.lbl_engine_note)
        self.btn_install_engine = make_button("Installer le moteur", name="btn_install_engine")
        self.btn_install_engine.setToolTip("Télécharge le programme et les modèles d'IA de TRELLIS.2. À faire une seule fois.")
        self.btn_install_engine.clicked.connect(self.on_install_engine)
        ev.addWidget(self.btn_install_engine)
        self.engine_row.setVisible(self.cmb_engine.count() > 1)
        sv.addWidget(self.engine_row)

        # qualité
        self.lbl_quality = text_label("Qualité", role="label")
        sv.addWidget(self.lbl_quality)
        self.cmb_quality = Segmented(accessible_name="Qualité")
        sv.addWidget(self.cmb_quality)
        self.lbl_quality_hint = text_label("", role="muted", wrap=True)
        sv.addWidget(self.lbl_quality_hint)

        # options de génération : des puces qui passent à la ligne quand la place manque
        sv.addWidget(text_label("Options de génération", role="label"))
        chips = QWidget()
        chips.setObjectName("transparent")
        flow = fx.FlowLayout(chips, 8, 8)
        self.chk_bg = fx.Chip("Retirer le fond")
        self.chk_bg.setChecked(True)
        self.chk_bg.setToolTip("Isole l'objet du décor avant de créer le modèle 3D.")
        self.chk_texture = fx.Chip("Texture très fine")
        self.chk_texture.setToolTip(
            "Expérimental. Texture de 4096 px décodée en 1024 : plus de détails dans les couleurs et les matériaux, mais plus de\n"
            "mémoire vidéo et de temps. Si la carte manque de mémoire, le logiciel refait le calcul avec la texture standard."
        )
        self.chk_color = fx.Chip("Colorier d'après l'image")
        self.chk_color.setChecked(True)
        self.chk_color.setToolTip(
            "TripoSG ne donne que la forme. Cette option projette les couleurs de ton image sur le modèle ;\n"
            "le dos et les zones cachées sont estimés (ils peuvent être approximatifs)."
        )
        for chip in (self.chk_bg, self.chk_texture, self.chk_color):
            flow.addWidget(chip)
        sv.addWidget(chips)

        # plus d'options (repliées par défaut)
        self.btn_more = make_button("Plus d'options", kind="ghost", icon="chevron-right", name="btn_more",
                                    icon_role="text-secondary")
        self.btn_more.setProperty("align", "left")
        self.btn_more.setCheckable(True)
        self.btn_more.toggled.connect(self._on_more_toggled)
        sv.addWidget(self.btn_more)
        self.more_box = QWidget()
        self.more_box.setObjectName("transparent")
        mv = QVBoxLayout(self.more_box)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(10)
        ratio_head = QHBoxLayout()
        self.lbl_ratio_title = text_label("Taille de l'objet dans l'image", role="label")
        self.lbl_ratio = text_label("85 %", role="caption")
        self.lbl_ratio.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ratio_head.addWidget(self.lbl_ratio_title, 1)
        ratio_head.addWidget(self.lbl_ratio)
        mv.addLayout(ratio_head)
        self.sld_ratio = QSlider(Qt.Orientation.Horizontal)
        self.sld_ratio.setRange(50, 100)
        self.sld_ratio.setSingleStep(5)
        self.sld_ratio.setPageStep(5)
        self.sld_ratio.setValue(85)
        self.sld_ratio.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.sld_ratio.setAccessibleName("Taille de l'objet dans l'image, en pourcentage")
        self.sld_ratio.setToolTip("Part de l'image occupée par l'objet une fois recadré. Plus grand = plus de détails.")
        self.sld_ratio.valueChanged.connect(self._update_ratio_label)
        mv.addWidget(self.sld_ratio)
        self._ratio_widgets = (self.lbl_ratio_title, self.lbl_ratio, self.sld_ratio)
        self.seed_row = QWidget()
        self.seed_row.setObjectName("transparent")
        sl = QHBoxLayout(self.seed_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(text_label("Numéro de variante", role="label"), 1)
        self.spn_seed = QSpinBox()
        self.spn_seed.setRange(0, 9999)
        self.spn_seed.setValue(42)
        self.spn_seed.setFixedWidth(theme.current().px(104))
        self.spn_seed.setAccessibleName("Numéro de variante")
        self.spn_seed.setToolTip("L'IA invente ce que l'image ne montre pas : une autre variante donne un autre résultat.")
        sl.addWidget(self.spn_seed)
        mv.addWidget(self.seed_row)
        self.variants_row = QWidget()
        self.variants_row.setObjectName("transparent")
        vl = QHBoxLayout(self.variants_row)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(text_label("Variantes à comparer", role="label"), 1)
        self.spn_variants = QSpinBox()
        self.spn_variants.setRange(1, 4)
        self.spn_variants.setValue(1)
        self.spn_variants.setFixedWidth(theme.current().px(104))
        self.spn_variants.setAccessibleName("Nombre de variantes à générer")
        self.spn_variants.setToolTip(
            "Génère plusieurs variantes à la suite (numéros 42, 43, 44…) et te laisse choisir la meilleure.\n"
            "L'IA invente ce que l'image ne montre pas : c'est souvent plus efficace que d'augmenter la qualité.\n"
            "Chaque variante prend plusieurs minutes."
        )
        vl.addWidget(self.spn_variants)
        mv.addWidget(self.variants_row)
        sv.addWidget(self.more_box)
        self.more_box.setVisible(False)
        lv.addWidget(self.settings_panel)
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
        fv.setContentsMargins(0, 4, 6, 0)
        fv.setSpacing(2)
        self.btn_generate = fx.GlowButton("Générer la 3D", kind="primary")
        self.btn_generate.setObjectName("btn_generate")
        icons.bind_icon(self.btn_generate, "arrow-right", "on-accent", size=22)
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
        rv.setSpacing(10)

        self.viewport = ViewportFrame()
        self.viewer = self.viewport.viewer
        self.btn_reset, self.btn_wire, self.btn_spin = self.viewport.btn_reset, self.viewport.btn_wire, self.viewport.btn_spin
        self.btn_turn, self.btn_flip = self.viewport.btn_turn, self.viewport.btn_flip
        self.seg_variant, self.lbl_variant = self.viewport.seg_variant, self.viewport.lbl_variant
        self.seg_variant.currentIndexChanged.connect(self._on_variant_changed)
        self.error_panel = self.viewport.error
        self.btn_reset.clicked.connect(self.viewer.reset_view)
        self.btn_wire.toggled.connect(self.viewer.set_wireframe)
        self.btn_spin.toggled.connect(self.viewer.set_auto_rotate)
        self.btn_turn.clicked.connect(lambda: self.on_rotate("turn"))
        self.btn_flip.clicked.connect(lambda: self.on_rotate("flip"))
        self.viewport.fullscreenRequested.connect(self.toggle_fullscreen)
        self.error_panel.retry.connect(self._on_retry)
        self.error_panel.back.connect(self._on_back)
        self.error_panel.copyDetails.connect(self._on_copy_details)
        self.error_panel.openLog.connect(self.on_open_log)
        rv.addWidget(self.viewport, 1)

        bar = fx.Panel("mixte", margin=8, cut=10)
        self._export_bar = bar
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(12)
        bh.addWidget(text_label("Format", role="label"))
        self.seg_format = Segmented(accessible_name="Format du fichier")
        self.seg_format.addItem("GLB : couleurs dans le fichier", "glb", label="GLB",
                                tooltip="Un seul fichier, avec les couleurs. Lisible partout.")
        self.seg_format.addItem("OBJ avec texture", "obj", label="OBJ", tooltip=OBJ_TIP)  # libellé court : trois formats doivent tenir à 1000 px
        self.seg_format.addItem("STL pour l'impression 3D", "stl", label="STL", tooltip=STL_TIP)
        self.seg_format.setMaximumWidth(theme.current().px(300))
        self.seg_format.currentIndexChanged.connect(self._on_format_changed)
        bh.addWidget(self.seg_format)
        bh.addStretch(1)
        self.btn_folder = IconButton("folder-open", "Afficher le dossier du fichier enregistré", name="btn_folder")
        self.btn_folder.clicked.connect(self.on_show_folder)
        self.btn_save = fx.GlowButton("Enregistrer sous…", kind="primary", tall=False, icon_after=False)
        self.btn_save.setObjectName("btn_save")
        icons.bind_icon(self.btn_save, "save", "on-accent")
        self.btn_save.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        h.setContentsMargins(28, 0, 24, 6)
        h.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.pills = QWidget()
        self.pills.setObjectName("transparent")
        pl = QHBoxLayout(self.pills)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.pill_image, self.pill_engine, self.pill_time = QLabel(), QLabel(), QLabel()
        for pill in (self.pill_image, self.pill_engine, self.pill_time):
            pill.setObjectName("infoPill")
            pill.setVisible(False)
            pl.addWidget(pill)
        pl.addStretch(1)
        left.addWidget(self.pills)
        self.status = ElidedLabel()
        self.status.setProperty("role", "secondary")
        left.addWidget(self.status)
        h.addLayout(left, 2)
        self.progress = IndeterminateBar()
        self.progress.setFixedWidth(theme.current().px(140))
        self.progress.setVisible(False)
        h.addWidget(self.progress)
        self.bubble = fx.Bubble()
        h.addWidget(self.bubble, 3)
        self.robot = fx.Robot(56)
        self.robot.clicked.connect(self._next_tip)
        h.addWidget(self.robot)
        return foot

    def _apply_metrics(self) -> None:
        """Tailles qui dépendent de l'échelle du texte."""
        t = theme.current()
        self._topbar.setFixedHeight(t.px(68))
        self._footer.setFixedHeight(t.px(84))
        self._left.setMinimumWidth(t.px(LEFT_PANEL_WIDTH[0]))
        self._left.setMaximumWidth(t.px(LEFT_PANEL_WIDTH[2]))
        self.splitter.setHandleWidth(t.px(14))
        self.seg_format.setMaximumWidth(t.px(300))
        for spin in (self.spn_seed, self.spn_variants):
            spin.setFixedWidth(t.px(104))
            spin.lineEdit().setTextMargins(t.px(12), 0, 0, 0)  # le style Fusion colle le texte au bord : marge explicite
        self.progress.setFixedWidth(t.px(140))
        self.setMinimumSize(t.px(1000), t.px(680))
        total = self.splitter.width() or self.width()
        left = min(max(t.px(self._left_base), t.px(LEFT_PANEL_WIDTH[0])), t.px(LEFT_PANEL_WIDTH[2]))
        self.splitter.setSizes([left, max(total - left, 1)])
        self._fit_footer()

    def _on_splitter_moved(self, *_args) -> None:
        t = theme.current()
        self._left_base = round(self.splitter.sizes()[0] / t.scale)

    def _initial_size(self) -> None:
        """Grande fenêtre par défaut, sans dépasser 90 % de l'écran (portables compacts)."""
        t = theme.current()
        width, height = t.px(1360), t.px(880)
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
            ("Ctrl+1", lambda: self.tabs.setCurrentIndex(TAB_STUDIO)),
            ("Ctrl+2", lambda: self.tabs.setCurrentIndex(TAB_CREATIONS)),
            ("Ctrl+3", lambda: self.tabs.setCurrentIndex(TAB_SETTINGS)),
            ("F11", self.toggle_fullscreen),
            ("Esc", self._on_escape),
        ):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # le focus clavier n'est visible qu'à l'usage du clavier : au démarrage il repose sur le fond, pas sur un bouton
        self.centralWidget().setFocus(Qt.FocusReason.OtherFocusReason)
        if not self._sized_once:
            self._sized_once = True
            self._apply_metrics()  # la largeur réelle n'est connue qu'à l'affichage : on y fixe la part du panneau de gauche
        enable_dark_titlebar(self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_topbar()
        self._fit_footer()

    def _fit_topbar(self) -> None:
        """Fenêtre étroite : l'accroche du logo disparaît pour laisser la place au nom du processeur graphique."""
        self.logo.set_compact(self.width() < theme.current().px(1160))

    # ---- réglages mémorisés -------------------------------------------------
    def _restore_settings(self) -> None:
        s = self.settings
        self.chk_bg.setChecked(s.value("remove_bg", True, type=bool))
        self.sld_ratio.setValue(s.value("ratio", 85, type=int))
        legacy_format = FMT_OBJ if s.value("bake", False, type=bool) else FMT_GLB  # anciens réglages : seulement « bake »
        self._format_pref = min(max(s.value("export_format", legacy_format, type=int), FMT_GLB), FMT_STL)
        self._set_format_index(self._format_pref)
        self._print = PrintOptions(
            height_mm=min(max(s.value("print_height", printing.DEFAULT_HEIGHT_MM, type=int), printing.HEIGHT_RANGE_MM[0]),
                          printing.HEIGHT_RANGE_MM[1]),
            flatten=s.value("print_flatten", True, type=bool),
        )
        self.chk_color.setChecked(s.value("colorize", True, type=bool))
        self.spn_seed.setValue(s.value("seed", 42, type=int))
        self.spn_variants.setValue(min(max(s.value("trellis_variants", 1, type=int), 1), 4))
        self.chk_texture.setChecked(s.value("trellis_texture", False, type=bool))
        saved_quant = s.value("trellis_quant", "", type=str)
        quant = saved_quant if saved_quant in QUANTS else self.engine.trellis_quant()
        self.engine.set_trellis_quant(quant)
        self.cmb_precision.blockSignals(True)
        self.cmb_precision.setCurrentIndex(max(self.cmb_precision.findData(quant), 0))
        self.cmb_precision.blockSignals(False)
        ids = [self.cmb_engine.itemData(i) for i in range(self.cmb_engine.count())]
        saved = s.value("engine_id", "", type=str)
        # premier lancement : TRELLIS.2 s'il est déjà installé, sinon TripoSR
        default = "trellis" if "trellis" in ids and self.engine.trellis_ready() else "triposr"
        self.cmb_engine.setCurrentIndex(ids.index(saved) if saved in ids else ids.index(default))
        self._on_engine_changed()  # remplit la liste des qualités du moteur choisi
        self.cmb_quality.setCurrentIndex(self._saved_quality(self._engine_id()))
        self._update_ratio_label()
        self.settings_panel.setExpanded(s.value("advanced_open", True, type=bool))
        self.btn_more.setChecked(s.value("more_options", False, type=bool))
        self._left_base = min(max(s.value("left_width", LEFT_PANEL_WIDTH[1], type=int), LEFT_PANEL_WIDTH[0]), LEFT_PANEL_WIDTH[2])
        self.settings_page.set_state(self.text_scale, self.reduce_motion, self.effects)

    def _saved_quality(self, engine_id: str) -> int:
        qualities, default, key, _label = ENGINE_QUALITY[engine_id]
        return min(max(self.settings.value(key, default, type=int), 0), len(qualities) - 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        s = self.settings
        s.setValue("remove_bg", self.chk_bg.isChecked())
        s.setValue("ratio", self.sld_ratio.value())
        s.setValue("engine_id", self._engine_id())
        s.setValue(ENGINE_QUALITY[self._engine_id()][2], self.cmb_quality.currentIndex())
        s.setValue("export_format", self._format_pref)
        s.setValue("bake", self._format_pref == FMT_OBJ)  # lu par les versions précédentes
        s.setValue("print_height", self._print.height_mm)
        s.setValue("print_flatten", self._print.flatten)
        s.setValue("colorize", self.chk_color.isChecked())
        s.setValue("seed", self.spn_seed.value())
        s.setValue("trellis_variants", self.spn_variants.value())
        s.setValue("trellis_texture", self.chk_texture.isChecked())
        s.setValue("trellis_quant", self.cmb_precision.currentData())
        s.setValue("text_scale", self.text_scale)
        s.setValue("reduce_motion", self.reduce_motion)
        s.setValue("effects", self.effects)
        s.setValue("advanced_open", self.settings_panel.isExpanded())
        s.setValue("more_options", self.btn_more.isChecked())
        s.setValue("left_width", int(self._left_base))
        self.viewer.set_auto_rotate(False)
        cancel_trellis()  # téléchargement ou calcul TRELLIS.2 en cours : arrêtés, la carte graphique est libérée
        self.pool.waitForDone(3000)
        super().closeEvent(event)

    # ---- apparence ----------------------------------------------------------
    def _reapply_theme(self) -> None:
        theme.apply_theme(QApplication.instance(), "dark", self.text_scale)
        self.viewer.apply_theme()
        self._refresh_ui()

    def _set_scale(self, scale: float) -> None:
        self.text_scale = scale
        self.settings.setValue("text_scale", scale)
        self._reapply_theme()

    def _repaint_everything(self) -> None:
        for widget in QApplication.instance().allWidgets():
            theme.repaint_later(widget)

    def _set_reduce_motion(self, reduced: bool) -> None:
        self.reduce_motion = reduced
        self.settings.setValue("reduce_motion", reduced)
        Motion.refresh(reduced, not self.effects)
        self.progress.setActive(False)
        self.progress.setActive(self._task is not None)
        self._repaint_everything()

    def _set_effects(self, on: bool) -> None:
        self.effects = on
        self.settings.setValue("effects", on)
        Motion.refresh(self.reduce_motion, not on)
        self._repaint_everything()

    def _on_more_toggled(self, shown: bool) -> None:
        self.more_box.setVisible(shown)
        icons.rebind_icon(self.btn_more, "chevron-down" if shown else "chevron-right", "text-secondary")

    def _on_tab(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == TAB_CREATIONS:
            self.creations_page.refresh()
        self._update_assistant()

    # ---- plein écran du visualiseur -------------------------------------------
    def toggle_fullscreen(self) -> None:
        """Le visualiseur prend toute la fenêtre (et tout l'écran) ; F11, Échap ou le bouton ramènent l'interface."""
        entering = not self._fullscreen
        if entering:
            self.tabs.setCurrentIndex(TAB_STUDIO)
            self._was_maximized = self.isMaximized()
        self._fullscreen = entering
        for part in (self._topbar, self._left, self._footer, self._export_bar):
            part.setVisible(not entering)
        self.splitter.setHandleWidth(0 if entering else theme.current().px(14))
        self.viewport.set_fullscreen_state(entering)
        if entering:
            self.showFullScreen()
        elif self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self._fit_footer()

    def _on_escape(self) -> None:
        if self._fullscreen:
            self.toggle_fullscreen()
        else:
            self.viewport.toast.dismiss()

    # ---- moteur -------------------------------------------------------------
    def _engine_id(self) -> str:
        return self.cmb_engine.currentData() or "triposr"

    def _qualities(self, engine_id: str):
        return ENGINE_QUALITY[engine_id][0]

    def _fill_quality(self, engine_id: str) -> None:
        self.cmb_quality.blockSignals(True)
        self.cmb_quality.clear()
        for label, value in self._qualities(engine_id):
            self.cmb_quality.addItem(label, value, label=label.split(" (")[0])
        self.cmb_quality.setCurrentIndex(ENGINE_QUALITY[engine_id][1])
        self.cmb_quality.blockSignals(False)
        self.lbl_quality.setText(ENGINE_QUALITY[engine_id][3])
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
            self.settings.setValue(ENGINE_QUALITY[previous][2], self.cmb_quality.currentIndex())
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
        active = self._active_engine()
        standing = active != "triposr"  # la sortie de TripoSR est redressée par le logiciel ; les autres se corrigent à la main
        self.btn_turn.setVisible(standing)
        self.btn_flip.setVisible(standing)
        # TripoSG exporte ses couleurs dans le GLB : pas de texture cuite
        colours_in_file = active == "triposg"
        self.seg_format.setItemEnabled(
            1, not colours_in_file,
            "Non disponible avec TripoSG : ses couleurs sont dans le fichier GLB." if colours_in_file else OBJ_TIP,
        )
        self._set_format_index(FMT_GLB if colours_in_file and self._format_pref == FMT_OBJ else self._format_pref)
        selected = self._engine_id()  # réglages de génération : suivent le moteur choisi
        self.chk_color.setVisible(selected == "triposg")
        self.seed_row.setVisible(selected in ("triposg", "trellis"))
        self.variants_row.setVisible(selected == "trellis")
        self.chk_texture.setVisible(selected == "trellis")
        self.precision_row.setVisible(selected == "trellis")
        for w in self._ratio_widgets:  # TRELLIS.2 cadre l'objet lui-même
            w.setVisible(selected != "trellis")
        text, tone = ENGINE_BADGES.get(selected, ("", "violet"))
        self.badge.setText(text)
        self.badge.setVisible(bool(text) and self.cmb_engine.count() > 1)
        set_prop(self.badge, "tone", tone)
        self._update_trellis_install()
        self._update_pills()
        self.viewport._layout_overlays()

    def _update_trellis_install(self) -> None:
        """Bouton et explication du moteur TRELLIS.2 : à installer une fois, puis prêt."""
        trellis = self._engine_id() == "trellis"
        ready = trellis and self.engine.trellis_ready()
        self.btn_install_engine.setVisible(trellis and not ready)
        self.lbl_engine_note.setVisible(trellis)
        if not trellis:
            return
        if ready:
            note = "Textures PBR (couleur, métal, rugosité) dans le fichier GLB. Demande une carte NVIDIA récente."
            if self.engine.trellis_quant() == "q8":
                note += " Précision haute : si la mémoire vidéo manque, repasse en Standard."
        else:
            size = human_size(max(self.engine.trellis_download_size(), 1))
            note = f"Premier usage : le moteur et ses modèles d'IA se téléchargent une seule fois (environ {size})."
            self.btn_install_engine.setText(f"Installer le moteur ({size})")
        self.lbl_engine_note.setText(note)

    def _on_precision_changed(self, *_args) -> None:
        self.engine.set_trellis_quant(self.cmb_precision.currentData())
        self._update_trellis_install()

    def _set_format_index(self, index: int) -> None:
        self._syncing_format = True
        self.seg_format.setCurrentIndex(index)
        self._syncing_format = False

    def _on_format_changed(self, index: int) -> None:
        if not self._syncing_format:
            self._format_pref = index

    def options(self) -> Options:
        engine_id = self._engine_id()
        return Options(
            remove_bg=self.chk_bg.isChecked(),
            ratio=self.sld_ratio.value() / 100.0,
            resolution=self._qualities(engine_id)[self.cmb_quality.currentIndex()][1],
            engine=engine_id,
            colorize=self.chk_color.isChecked(),
            seed=self.spn_seed.value(),
            texture="fine" if self.chk_texture.isChecked() else "standard",
            variants=self.spn_variants.value(),
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
        for w in (self.cmb_engine, self.cmb_quality, self.chk_bg, self.sld_ratio, self.chk_color, self.spn_seed,
                  self.btn_install_engine, self.cmb_precision, self.chk_texture, self.spn_variants, self.seg_variant):  # les réglages sont lus au lancement : les figer évite un calcul incohérent
            w.setEnabled(not busy)
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

        if self._task_kind in ("generate", "install") and busy:
            page = ViewportFrame.BUSY
        elif error:
            page = ViewportFrame.ERROR
        elif has_result:
            page = ViewportFrame.RESULT
        else:
            page = ViewportFrame.EMPTY
        if page != self.viewport.page_name():
            self.viewport.show_page(page)
        self._update_assistant()
        self._fit_footer()

    # ---- pied de page : pastilles et assistant -----------------------------------
    def _update_pills(self) -> None:
        if not hasattr(self, "pill_image"):
            return
        image = f"Image : {self.input_image.width} × {self.input_image.height}" if self.input_image is not None else ""
        engine = f"Moteur : {ENGINE_NAMES.get(self._engine_id(), '')}"
        duration = f"Dernière génération : {format_duration(self._last_duration)}" if self._last_duration is not None else ""
        for pill, text in ((self.pill_image, image), (self.pill_engine, engine), (self.pill_time, duration)):
            pill.setText(text)
            pill.setAccessibleName(text)
            pill.setVisible(bool(text))
        self._fit_footer()

    def _fit_footer(self) -> None:
        """Sur une fenêtre étroite, les pastilles disparaissent l'une après l'autre plutôt que d'être coupées."""
        if not hasattr(self, "pill_image"):
            return
        t = theme.current()
        pills = [p for p in (self.pill_image, self.pill_engine, self.pill_time) if p.text()]
        room = int(self._footer.width() * 0.6) - t.px(60)
        used = 0
        for pill in pills:
            need = pill.sizeHint().width() + t.px(8)
            fits = used + need <= room
            pill.setVisible(fits)
            used += need if fits else 0
        self.pills.setVisible(any(p.text() for p in pills) and used > 0)

    def _assistant_text(self) -> str:
        if self._tip_override:
            return self._tip_override
        if self._task is not None:
            return {"install": "J'installe le moteur : une seule fois, laisse la fenêtre ouverte.",
                    "save": "J'écris le fichier, encore un instant."}.get(
                self._task_kind or "", "Je m'en occupe : le calcul tourne sur ton ordinateur.")
        if self._error is not None:
            return "Ça n'a pas marché. Lis le message, puis réessaie ou ouvre le journal."
        if self.result is not None:
            return "Tourne le modèle à la souris, choisis un format, puis enregistre-le."
        if self.input_image is not None:
            return "Image prête. Clique sur « Générer la 3D » pour lancer le calcul."
        return "Dépose une image pour commencer. Un objet net sur un fond simple marche le mieux."

    def _update_assistant(self) -> None:
        if hasattr(self, "bubble"):
            self.bubble.set_text(self._assistant_text())

    def _next_tip(self) -> None:
        self._tip_override = TIPS[self._tip_index % len(TIPS)]
        self._tip_index += 1
        self._update_assistant()
        QTimer.singleShot(14000, self._clear_tip)

    def _clear_tip(self) -> None:
        self._tip_override = ""
        self._update_assistant()

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
        self.tabs.setCurrentIndex(TAB_STUDIO)
        self.input_image = image
        self.drop.set_image(image)
        # une nouvelle image rend l'ancien modèle caduc : on repart d'un état propre
        self.result = None
        self.variants = []
        self._fill_variant_selector()
        self._error = None
        self.viewer.clear()
        self.viewport.set_info("")
        self.viewport.busy.set_source(None)
        self._update_engine_widgets()
        self._refresh_ui()
        self.set_status(f"Image chargée ({image.width} × {image.height}). Clique sur « Générer la 3D ».")
        tips = check_image(image)  # conseils seulement : une image n'est jamais refusée
        if tips:
            self.toast("Conseil : " + " ".join(tips), "warning", 12000)

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
        if self._first_image_url(event):
            event.acceptProposedAction()
            self.tabs.setCurrentIndex(TAB_STUDIO)
            self.drop.set_dragging(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.set_dragging(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop.set_dragging(False)
        path = self._first_image_url(event)
        if path and self._task is None:
            self.load_path(path)
            event.acceptProposedAction()

    # ---- tâches -------------------------------------------------------------
    def run_task(self, fn, on_done, on_partial=None, kind: str = "generate", retry=None) -> None:
        if self._task is not None:
            return
        task = Task(fn)
        task.signals.progress.connect(self.set_status)
        task.signals.partial.connect(self._task_partial)
        task.signals.finished.connect(self._task_finished)
        task.signals.failed.connect(self._task_failed)
        self._task, self._on_done, self._on_partial = task, on_done, on_partial
        self._task_kind, self._retry, self._error = kind, retry, None
        self._tip_override = ""
        self.viewport.toast.hide_now()
        titles = {"generate": "Génération en cours", "preview": "Détourage en cours", "save": "Export en cours",
                  "install": "Installation du moteur en cours"}
        self.viewport.busy.title.setText(titles.get(kind, "Travail en cours"))
        # la reconstruction animée part de l'image envoyée au moteur ; sans image (installation), le globe tourne
        self.viewport.busy.set_source(self.input_image if kind == "generate" else None)
        self._gen_started = time.monotonic() if kind == "generate" else None
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
        self._update_assistant()

    def _task_failed(self, message: str, details: str) -> None:
        kind = self._task_kind or "generate"
        self._task = self._on_done = self._on_partial = None
        self._task_kind = None
        self._gen_started = None
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

    def on_open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.DATA_DIR)))

    def on_open_creation(self, path: str) -> None:
        if Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.toast("Ce fichier est introuvable : il a été déplacé ou supprimé.", "warning")
            self.creations_page.refresh()

    def on_show_creation_folder(self, path: str) -> None:
        folder = Path(path).parent
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self.toast("Ce dossier est introuvable.", "warning")

    def on_copy_prompt(self) -> None:
        QGuiApplication.clipboard().setText(IMAGE_PROMPT)
        self.tabs.setCurrentIndex(TAB_STUDIO)
        self.toast("Prompt copié. Colle-le dans ChatGPT en remplaçant les crochets par ta description : "
                   "tu obtiendras une image de départ idéale pour la 3D.", "success", 9000)

    def on_open_licences(self) -> None:
        for candidate in (paths.APP_ROOT / "licenses" / "THIRD_PARTY_NOTICES.md", paths.APP_ROOT / "THIRD_PARTY_NOTICES.md"):
            if candidate.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                return
        self.toast("Le fichier des licences est introuvable dans cette installation.", "warning")

    # ---- actions ------------------------------------------------------------
    def _require_image(self) -> bool:
        if self.input_image is None:
            self.tabs.setCurrentIndex(TAB_STUDIO)
            self.set_status("Dépose d'abord une image (glisser-déposer, Ctrl+O ou Ctrl+V).")
            self.toast("Dépose d'abord une image : glisse-la dans la fenêtre, Ctrl+O pour choisir, Ctrl+V pour coller.",
                       "warning")
            return False
        return True

    def show_prepared(self, image: Image.Image) -> None:
        self.drop.set_prepared(image)
        self.viewport.busy.set_source(image)  # la reconstruction reprend l'image détourée

    def _on_view_changed(self, index: int) -> None:
        """La bascule « Détourée » demande l'aperçu s'il n'a pas encore été calculé."""
        if index == 1 and not self.drop.has_prepared() and self._task is None and self.input_image is not None:
            self.on_preview()

    def on_preview(self) -> None:
        if not self._require_image():
            return
        opts, image, engine = self.options(), self.input_image, self.engine

        def job(progress, partial):
            if opts.engine == "trellis":
                return engine.prepare_trellis(image, opts.remove_bg, opts.ratio, progress)
            if opts.engine == "triposg":
                return engine.prepare_triposg(image, opts.remove_bg, opts.ratio, progress)[0]
            return engine.preprocess(image, opts.remove_bg, opts.ratio, progress)

        def done(prepared):
            self.drop.set_prepared(prepared)
            self.set_status("Aperçu prêt. Si le détourage est mauvais, essaie une autre image ou désactive-le.")

        self.run_task(job, done, kind="preview", retry=self.on_preview)

    def on_install_engine(self) -> None:
        """Télécharge le programme et les poids de TRELLIS.2 (une seule fois ; la reprise est automatique)."""
        if self._task is not None:
            return
        engine = self.engine

        def job(progress, partial):
            engine.install_trellis(progress)
            return True

        def done(_result):
            self._update_trellis_install()
            self.set_status("Moteur TRELLIS.2 installé. Choisis une image et clique sur « Générer la 3D ».")
            self.toast("Moteur Qualité maximale installé.", "success")

        self.run_task(job, done, kind="install", retry=self.on_install_engine)

    def on_generate(self) -> None:
        if self._task is not None:
            return
        if not self._require_image():
            return
        opts, image, engine = self.options(), self.input_image, self.engine
        if opts.engine == "triposg" and not engine.triposg_ready():
            self.toast(INSTALL_HINT, "warning", 9000)
            return
        if opts.engine == "trellis" and not engine.trellis_ready():
            self.toast(NOT_INSTALLED, "warning", 9000)
            self._update_trellis_install()
            return

        def job(progress, partial):
            if opts.engine == "trellis":
                done, problems = [], []
                for k in range(opts.variants):
                    prefix = f"Variante {k + 1} sur {opts.variants} : " if opts.variants > 1 else ""
                    try:
                        made = engine.generate_trellis(
                            image, opts.resolution, opts.remove_bg, opts.seed + k,
                            lambda message, prefix=prefix: progress(prefix + message), opts.texture,
                        )
                    except Exception as exc:  # noqa: BLE001 - les variantes déjà terminées sont gardées
                        if not done:
                            raise
                        log.warning("Variante %s non terminée", k + 1, exc_info=True)
                        problems.append(f"La variante {k + 1} n'a pas abouti : {str(exc).splitlines()[0]}")
                        break
                    done.append({"engine": "trellis", "prepared": None, "mesh": made["mesh"], "mesh_export": made["mesh"],
                                 "glb": made["glb"], "scene_codes": None, "extra": IDENTITY.copy(), "notes": made["notes"],
                                 "seed": opts.seed + k, "res": made.get("res"), "fine": made.get("fine", False)})
                return {"engine": "trellis", "variants": done, "problems": problems}
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
        if self._gen_started is not None:
            self._last_duration = time.monotonic() - self._gen_started
            self._gen_started = None
        self.variants = result.get("variants") or [result]
        self._problems = list(result.get("problems") or [])
        self._error = None
        self._fill_variant_selector()
        self._show_variant(0)
        self.viewport.play_reveal(self.drop.pixmap())  # l'image se dissout, le modèle apparaît dessous
        self._update_pills()

    def _fill_variant_selector(self) -> None:
        """Sélecteur « Variante » sous le modèle : seulement quand plusieurs variantes ont été générées."""
        self._syncing_variant = True
        self.seg_variant.clear()
        for index in range(len(self.variants) if len(self.variants) > 1 else 0):
            seed = self.variants[index].get("seed")
            tip = f"Variante {index + 1}" + (f" (numéro {seed})" if seed is not None else "")
            self.seg_variant.addItem(tip, index, label=str(index + 1), tooltip=tip)
        self._syncing_variant = False
        self.viewport.show_variants(self.seg_variant.count() > 1)

    def _on_variant_changed(self, index: int) -> None:
        if self._syncing_variant or self._task is not None or not 0 <= index < len(self.variants):
            return
        self._show_variant(index)

    def _show_variant(self, index: int) -> None:
        """Affiche la variante `index` (la première, juste après un calcul) et met à jour l'état, la pastille, la ligne d'état."""
        result = self.variants[index]
        self.result = result
        if result["prepared"] is not None:
            self.drop.set_prepared(result["prepared"])
        mesh = result["mesh"]
        self.viewer.set_mesh(mesh, orientation=self._orientation(result))
        if self.seg_variant.count() > 1:
            self._syncing_variant = True
            self.seg_variant.setCurrentIndex(index)
            self._syncing_variant = False
        self._update_engine_widgets()
        self._refresh_ui()  # réactive Enregistrer et les boutons de rotation
        full = result["mesh_export"] if result["mesh_export"] is not None else mesh
        count = f"{len(full.vertices):,}".replace(",", " ")
        engine_name = ENGINE_NAMES.get(result["engine"], "TripoSR")
        many = len(self.variants) > 1
        # l'essentiel d'abord : sur une fenêtre étroite, la fin de la pastille est retirée
        chip = f"variante {index + 1}/{len(self.variants)} · " if many else ""
        chip += f"{count} sommets · {engine_name}"
        if result.get("res"):
            chip += f" · {result['res']}"
        self.viewport.set_info(chip)
        extra = (
            " Si l'objet apparaît couché ou de côté, utilise « Redresser » ou « Pivoter 90° »."
            if result["engine"] != "triposr" else ""
        )
        notes = " ".join([*(result.get("notes") or []), *(self._problems if index == len(self.variants) - 1 else [])])
        if many:
            seed = result.get("seed")
            ready = (f"Variante {index + 1} sur {len(self.variants)}" + (f" (numéro {seed})" if seed is not None else "")
                     + f" : {count} sommets. Compare-les avec le sélecteur « Variante », puis « Enregistrer sous… ».{extra}")
        else:
            ready = f"Modèle prêt ({count} sommets). Tourne-le à la souris, puis « Enregistrer sous… ».{extra}"
        # les remarques d'abord : la ligne d'état est coupée à droite quand elle est trop longue
        self.set_status(f"{notes}  {ready}".strip())

    def on_rotate(self, kind: str) -> None:
        if self.result is None or self._task is not None or self.result["engine"] == "triposr":
            return
        step = rotation("y", 90) if kind == "turn" else rotation("x", -90)
        for variant in self.variants or [self.result]:  # même sortie du moteur : la correction vaut pour toutes les variantes
            variant["extra"] = step @ variant["extra"]
        self.viewer.set_mesh(self.result["mesh"], orientation=self._orientation(self.result))

    def on_save(self) -> None:
        if self.result is None or self._task is not None:
            return
        fmt = self.seg_format.currentIndex()
        stl = fmt == FMT_STL
        bake = fmt == FMT_OBJ and self.result["engine"] in ("triposr", "trellis")
        print_options = self._ask_print_options() if stl else None
        if stl and print_options is None:
            return  # fenêtre « Impression 3D » annulée
        folder = self.settings.value("last_save_dir", str(Path.home()))
        suffix = ".stl" if stl else (".obj" if bake else ".glb")
        shown = next((i for i, v in enumerate(self.variants) if v is self.result), None)  # identité : les dicts contiennent des tableaux
        variant_tag = f"_v{shown + 1}" if len(self.variants) > 1 and shown is not None else ""
        if stl:
            filters = "Modèle STL pour l'impression 3D (*.stl)"
        else:
            filters = "Modèle OBJ (*.obj);;Modèle GLB (*.glb)" if bake else "Modèle GLB (*.glb);;Modèle OBJ (*.obj)"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le modèle 3D", str(Path(folder) / f"{self.input_name}{variant_tag}{suffix}"), filters
        )
        if not chosen:
            return
        path = Path(chosen)
        if (stl and path.suffix.lower() != ".stl") or (not stl and path.suffix.lower() not in (".glb", ".obj")):
            path = path.with_suffix(suffix)
        self.settings.setValue("last_save_dir", str(path.parent))
        result, engine = self.result, self.engine

        def job(progress, partial):
            if print_options is not None:
                return engine.export_print(result, path, print_options, progress)
            if result["engine"] == "trellis":
                return engine.export_trellis(result, path, progress)
            if result["engine"] == "triposg":
                return engine.export_triposg(result, path, progress)
            return engine.export(result["mesh"], result["scene_codes"], path, bake, progress)

        self.run_task(job, lambda out: self._saved(out, bake), kind="save", retry=self.on_save)

    def _ask_print_options(self) -> PrintOptions | None:
        """Fenêtre « Impression 3D » : hauteur et aplatissement. None si elle est annulée."""
        try:  # l'annonce de la taille au sol est facultative : sans elle, la fenêtre indique seulement la hauteur
            ratios = printing.size_ratios(self.result["mesh"], self._orientation(self.result))
        except Exception:  # noqa: BLE001
            log.debug("Proportions du modèle indisponibles", exc_info=True)
            ratios = None
        dialog = PrintDialog(self, ratios, self._print)
        enable_dark_titlebar(dialog)
        if not dialog.exec():
            return None
        self._print = dialog.values()
        return self._print

    def _saved(self, out, baked: bool = False) -> None:
        report = None
        if isinstance(out, tuple):  # export STL : (chemin, rapport de réparation)
            out, report = out
        self.last_saved = Path(out)
        self._refresh_ui()
        extra = " (avec son image de texture)" if self.last_saved.suffix.lower() == ".obj" and baked else ""
        if report is None:
            self.set_status(f"Enregistré : {self.last_saved}{extra}")
            self.toast(f"Enregistré : {self.last_saved.name}{extra}", "success")
        elif report.watertight:
            self.set_status(f"Enregistré : {self.last_saved}. {report.summary()}.")
            self.toast(f"Enregistré : {self.last_saved.name} · {report.summary()}", "success", 9000)
        else:  # le fichier est écrit, mais la personne doit savoir qu'il demande une réparation (sans boîte de dialogue modale)
            self.set_status(f"Enregistré : {self.last_saved}. {report.lines()[0]}")
            self.toast(f"Enregistré : {self.last_saved.name} · {report.summary()}", "warning", 12000)
            self._tip_override = STL_OPEN_HINT
            self._update_assistant()
            QTimer.singleShot(14000, self._clear_tip)
        self._remember_creation(self.last_saved)

    def _remember_creation(self, path: Path) -> None:
        """Ajoute le fichier à « Mes créations » (avec l'image de départ en vignette). Sans conséquence si la liste échoue."""
        result = self.result
        if result is None:
            return
        full = result["mesh_export"] if result["mesh_export"] is not None else result["mesh"]
        facts = [f"{len(full.vertices):,} sommets".replace(",", " ")]
        if result.get("res"):
            facts.insert(0, str(result["res"]))
        self.store.add(path, engine=ENGINE_NAMES.get(result["engine"], "TripoSR"), info=" · ".join(facts),
                       thumbnail=self.input_image)
        self.creations_page.refresh()

    def on_show_folder(self) -> None:
        if self.last_saved is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_saved.parent)))


# =============================================================================
#  Démarrage
# =============================================================================
def migrate_legacy_settings(settings: QSettings, legacy: QSettings | None = None) -> bool:
    """Reprend les réglages de l'ancien nom du logiciel (« Image vers 3D ») la première fois, sans jamais écraser les nouveaux."""
    legacy = legacy if legacy is not None else QSettings("ImageVers3D", "Studio")
    if settings.allKeys() or not legacy.allKeys():
        return False
    for key in legacy.allKeys():
        settings.setValue(key, legacy.value(key))
    settings.sync()
    return True


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
    app.setApplicationName("ThreeRex")
    settings = QSettings("ThreeRex", "Studio")
    migrate_legacy_settings(settings)
    Motion.refresh(settings.value("reduce_motion", False, type=bool), not settings.value("effects", True, type=bool))
    theme.apply_theme(app, "dark", settings.value("text_scale", 1.0, type=float))

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
                "(dossier « ThreeRex »), ou réinstalle l'application.",
            )
            return 1
        engine = Engine()

    window = MainWindow(engine, settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
