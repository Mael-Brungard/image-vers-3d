"""Vérificateur de mise en page : parcourt chaque page, plusieurs tailles de fenêtre et les trois tailles de texte, et
signale tout ce qu'un œil humain verrait comme un défaut : texte coupé, éléments qui se chevauchent, contenu qui sort de son
cadre, défilement horizontal, bulle de l'assistant tronquée.

Lancé avec QT_QPA_PLATFORM=offscreen (moteur factice, ni GPU ni PyTorch) :  python tests/scenarios/layout_audit.py
Sortie : « OK » si rien n'est signalé, sinon la liste des problèmes (état, taille, texte) et un code de retour 1.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("THREEREX_DATA", str(Path(tempfile.mkdtemp(prefix="trx_audit_data_"))))

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QScrollArea,
    QSlider,
    QSpinBox,
    QWidget,
)

from threerex import fx, studio, theme
from threerex.creations import CreationStore
from threerex.print_dialog import PrintDialog
from threerex.printing import HEIGHT_RANGE_MM, PrintOptions
from threerex.widgets import ElidedLabel

fx.Clock.require_active = False

SIZES = ((1000, 680), (1180, 760), (1360, 880), (1920, 1040))
SCALES = (1.0, 1.15, 1.3)
TOL = 1  # pixels de tolérance (arrondis)


class AuditEngine:
    """Moteur factice : tout est « prêt » pour que chaque réglage de l'interface soit visible."""

    def triposg_ready(self):
        return True

    def trellis_supported(self):
        return True

    def trellis_ready(self):
        return self.ready

    def trellis_download_size(self):
        return 7_200_000_000

    def trellis_quant(self):
        return "q4"

    def set_trellis_quant(self, quant):
        pass

    def install_trellis(self, progress):
        self.ready = True

    def device_label(self):
        return "GPU : NVIDIA GeForce RTX 4070 Ti"

    def __init__(self):
        self.ready = False

    def preprocess(self, image, remove_bg, ratio, progress):
        return image.convert("RGB")

    def prepare_trellis(self, image, remove_bg, ratio, progress):
        return image.convert("RGB")

    def generate(self, prepared, resolution, progress):
        mesh = trimesh.creation.icosphere(subdivisions=3)
        colors = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
        colors[:] = (200, 90, 50, 255)
        mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=colors)
        return mesh, None

    def generate_trellis(self, image, quality, remove_bg, seed, progress, texture="standard"):
        mesh = trimesh.creation.icosphere(subdivisions=3)
        return {"glb": b"", "mesh": mesh, "notes": ["Remarque."], "res": 1024, "fine": False}


def test_image():
    img = Image.new("RGB", (900, 700), (236, 232, 226))
    ImageDraw.Draw(img).polygon([(300, 130), (600, 130), (700, 420), (560, 640), (340, 640), (200, 420)], fill=(190, 92, 52))
    return img.convert("RGBA")


# --------------------------------------------------------------------------------------------------------------------
#  Contrôles
# --------------------------------------------------------------------------------------------------------------------
def describe(widget: QWidget) -> str:
    name = widget.objectName()
    text = ""
    if hasattr(widget, "text"):
        try:
            text = widget.text()
        except Exception:  # noqa: BLE001
            text = ""
    return f"{type(widget).__name__}{'#' + name if name else ''}{' « ' + text[:40] + ' »' if text else ''}"


def visible_descendants(root: QWidget):
    for w in root.findChildren(QWidget):
        if w.isVisible() and w.width() > 0 and w.height() > 0:
            yield w


def in_scroll_content(widget: QWidget) -> bool:
    """Vrai pour le contenu d'une zone défilante : il peut dépasser la fenêtre (on le fait défiler)."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent.parentWidget(), QScrollArea) or (
            parent.parentWidget() is not None and isinstance(parent.parentWidget().parentWidget(), QScrollArea)
        ):
            return True
        parent = parent.parentWidget()
    return False


def check_text_fits(widget: QWidget):
    """Un libellé court ne doit pas être coupé ; un texte qui passe à la ligne doit avoir toute sa hauteur."""
    if isinstance(widget, ElidedLabel):
        return
    if isinstance(widget, QLabel) and widget.text():
        if widget.wordWrap():
            need = widget.heightForWidth(widget.width())
            if need > widget.height() + TOL:
                yield f"texte coupé en hauteur ({widget.height()} px pour {need} px) : {describe(widget)}"
        elif widget.pixmap() is None or widget.pixmap().isNull():
            need = widget.sizeHint().width()
            if widget.width() + TOL < need:
                yield f"libellé trop étroit ({widget.width()} px pour {need} px) : {describe(widget)}"
    elif isinstance(widget, (QAbstractButton,)) and getattr(widget, "text", None) and widget.text():
        need = widget.sizeHint().width()
        if widget.width() + TOL < need and widget.sizePolicy().horizontalPolicy() != widget.sizePolicy().Policy.Ignored:
            yield f"bouton trop étroit ({widget.width()} px pour {need} px) : {describe(widget)}"
    # une largeur ou une hauteur imposée (boutons d'icône, compteurs) est voulue ; la vérification des textes se fait plus bas
    fixed_w = widget.minimumWidth() == widget.maximumWidth() and widget.minimumWidth() > 0
    fixed_h = widget.minimumHeight() == widget.maximumHeight() and widget.minimumHeight() > 0
    if isinstance(widget, QSpinBox) and fixed_w:
        # le compteur a une largeur imposée : on vérifie que sa plus grande valeur y tient (texte + marges + flèches)
        fm = QFontMetrics(widget.font())
        need = fm.horizontalAdvance(str(widget.maximum())) + 2 * round(12 * theme.current().scale) + round(34 * theme.current().scale)
        if widget.width() + TOL < need:
            yield f"{describe(widget)} trop étroit pour sa plus grande valeur ({widget.width()} px pour {need} px)"
        return
    if isinstance(widget, (QComboBox, QSpinBox, QSlider)) or type(widget).__module__.startswith("threerex"):
        hint = widget.minimumSizeHint()
        if (not fixed_w and widget.width() + TOL < hint.width()) or (not fixed_h and widget.height() + TOL < hint.height()):
            yield (f"{describe(widget)} plus petit que sa taille minimale "
                   f"({widget.width()}×{widget.height()} pour {hint.width()}×{hint.height()})")


def check_inside_parent(widget: QWidget, window: QWidget):
    parent = widget.parentWidget()
    if parent is None or widget.isWindow() or in_scroll_content(widget):
        return
    if isinstance(parent, QScrollArea) or type(parent).__name__ in ("QWidget",) and parent.objectName() == "qt_scrollarea_viewport":
        return
    if widget.objectName().startswith("qt_"):
        return
    rect = widget.geometry()
    if rect.left() < -TOL or rect.top() < -TOL or rect.right() > parent.width() + TOL or rect.bottom() > parent.height() + TOL:
        yield f"{describe(widget)} sort de son cadre {describe(parent)} ({rect.x()},{rect.y()} {rect.width()}×{rect.height()} dans {parent.width()}×{parent.height()})"
    top = widget.mapTo(window, widget.rect().topLeft())
    if top.x() + widget.width() > window.width() + TOL or top.y() + widget.height() > window.height() + TOL:
        yield f"{describe(widget)} dépasse de la fenêtre"


# Parents dont les enfants se superposent par construction (calques du visualiseur, pages empilées)
OVERLAY_PARENTS = ("ViewportFrame", "QStackedWidget", "QStackedLayout", "ParticleField")


def check_siblings(root: QWidget):
    seen = set()
    for parent in [root, *root.findChildren(QWidget)]:
        if not parent.isVisible() or type(parent).__name__ in OVERLAY_PARENTS:
            continue
        if parent.objectName() == "dropzone":  # deux pages empilées, une seule visible
            continue
        kids = [c for c in parent.children() if isinstance(c, QWidget) and c.isVisible() and not c.isWindow()
                and not c.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) and not c.objectName().startswith("qt_")]
        for i, a in enumerate(kids):
            for b in kids[i + 1:]:
                inter = a.geometry().intersected(b.geometry())
                if inter.width() > 2 and inter.height() > 2 and (id(a), id(b)) not in seen:
                    seen.add((id(a), id(b)))
                    yield f"{describe(a)} et {describe(b)} se chevauchent ({inter.width()}×{inter.height()} px) dans {describe(parent)}"


def check_viewport_overlays(win):
    vp = win.viewport
    names = ("info", "help", "toolbar", "modebar", "variant_bar")
    overlays = [(n, getattr(vp, n)) for n in names if getattr(vp, n).isVisible()]
    for i, (na, a) in enumerate(overlays):
        if not QRect(0, 0, vp.width(), vp.height()).contains(a.geometry()):
            yield f"calque « {na} » hors du visualiseur ({a.geometry().getRect()} dans {vp.width()}×{vp.height()})"
        for nb, b in overlays[i + 1:]:
            inter = a.geometry().intersected(b.geometry())
            if inter.width() > 2 and inter.height() > 2:
                yield f"calques « {na} » et « {nb} » se chevauchent ({inter.width()}×{inter.height()} px)"
    # le contenu des pages (texte, touches) ne passe pas sous un calque
    page = vp.stack.currentWidget()
    for w in page.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w, (QLabel,)) or not getattr(w, "text", lambda: "")():
            continue
        spot = QRect(w.mapTo(vp, w.rect().topLeft()), w.size())
        for n, a in overlays:
            inter = spot.intersected(a.geometry())
            if inter.width() > 2 and inter.height() > 2:
                yield f"le texte « {w.text()[:30]} » passe sous le calque « {n} »"


def check_scroll_areas(root: QWidget):
    for area in root.findChildren(QScrollArea):
        if area.isVisible() and area.horizontalScrollBar().maximum() > 0:
            yield f"défilement horizontal dans {describe(area)} (de {area.horizontalScrollBar().maximum()} px)"


def check_elisions(win):
    chip = win.chip._text
    fm = QFontMetrics(chip.font())
    if chip.isVisible() and fm.horizontalAdvance(chip.text()) > chip.width() + TOL:
        yield f"nom de la carte graphique coupé dans la barre du haut ({chip.width()} px pour {fm.horizontalAdvance(chip.text())} px)"
    for pill in (win.pill_image, win.pill_engine, win.pill_time):
        if pill.isVisible() and pill.width() + TOL < pill.sizeHint().width():
            yield f"pastille coupée : {pill.text()}"
    bubble = win.bubble
    if bubble.isVisible() and hasattr(bubble, "is_elided") and bubble.is_elided():
        yield f"bulle de l'assistant tronquée : « {bubble.text()} »"


def check_print_dialog(parent, label: str) -> list[str]:
    """La fenêtre « Impression 3D » à la taille de texte courante : rien de coupé, rien qui se chevauche, hauteur qui suit le contenu."""
    problems = []
    for ratios in ((0.82, 0.55), None):  # avec et sans annonce de la taille au sol
        dialog = PrintDialog(parent, ratios, PrintOptions())
        dialog.show()
        for value in (HEIGHT_RANGE_MM[1], HEIGHT_RANGE_MM[0]):  # les textes les plus longs et les plus courts
            dialog.spn_height.setValue(value)
            QTest.qWait(30)
            for widget in visible_descendants(dialog):
                problems.extend(check_text_fits(widget))
                problems.extend(check_inside_parent(widget, dialog))
            problems.extend(check_siblings(dialog))
            need = dialog.layout().totalHeightForWidth(dialog.width())
            if dialog.height() + TOL < need:
                problems.append(f"fenêtre trop basse pour son contenu ({dialog.height()} px pour {need} px)")
            if dialog.btn_ok.mapTo(dialog, dialog.btn_ok.rect().bottomRight()).y() > dialog.height():
                problems.append("bouton « Continuer » hors de la fenêtre")
        dialog.close()
    return [f"[{label} · fenêtre Impression 3D] {p}" for p in dict.fromkeys(problems)]


def check_window(win, label: str):
    problems = []
    for widget in visible_descendants(win):
        for p in check_text_fits(widget):
            problems.append(p)
        for p in check_inside_parent(widget, win):
            problems.append(p)
    problems.extend(check_siblings(win.centralWidget()))
    problems.extend(check_scroll_areas(win))
    problems.extend(check_elisions(win))
    if win.pages.currentIndex() == 0 and win.viewport.isVisible():
        problems.extend(check_viewport_overlays(win))
        if win.viewport.width() < theme.current().px(480):
            problems.append(f"visualiseur trop étroit ({win.viewport.width()} px)")
    return [f"[{label}] {p}" for p in dict.fromkeys(problems)]


# --------------------------------------------------------------------------------------------------------------------
#  Parcours
# --------------------------------------------------------------------------------------------------------------------
def wait_idle(win, seconds=10.0):
    end = time.time() + seconds
    while win._task is not None and time.time() < end:
        QTest.qWait(20)
    QTest.qWait(60)


def run() -> list[str]:
    run.app = QApplication.instance() or QApplication([])  # référence gardée : Qt plante si l'objet est libéré
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "reglages.ini"), QSettings.Format.IniFormat)
    store_dir = Path(tempfile.mkdtemp(prefix="trx_audit_store_"))
    store = CreationStore(store_dir)
    for i, name in enumerate(("vase.glb", "un_nom_de_fichier_vraiment_tres_long_pour_tester_la_coupure.obj", "lampe.glb")):
        f = store_dir / name
        f.write_bytes(b"x" * 90000 * (i + 1))
        store.add(f, engine="TRELLIS.2" if i % 2 == 0 else "TripoSR", info="1024 · 412 380 sommets", thumbnail=test_image())
    (store_dir / "lampe.glb").unlink()  # une carte « Fichier introuvable »

    engine = AuditEngine()
    win = studio.MainWindow(engine, settings, store)
    win.show()
    QTest.qWait(150)
    problems: list[str] = []
    ids = [win.cmb_engine.itemData(i) for i in range(win.cmb_engine.count())]
    assert {"triposr", "trellis", "triposg"} <= set(ids), ids

    for scale in SCALES:
        win._set_scale(scale)
        for width, height in SIZES:
            t = theme.current()
            w, h = max(width, t.px(1000)), max(height, t.px(680))
            win.resize(w, h)
            QTest.qWait(80)

            def audit(state: str):
                QTest.qWait(40)
                problems.extend(check_window(win, f"{w}×{h} · texte {int(scale * 100)} % · {state}"))

            # --- vue principale, sans image
            win.tabs.setCurrentIndex(0)
            win.btn_more.setChecked(False)
            for engine_id in ("triposr", "trellis", "triposg"):
                win.cmb_engine.setCurrentIndex(ids.index(engine_id))
                audit(f"vide / {engine_id}")
            # --- réglages dépliés (toutes les lignes visibles) puis repliés
            win.cmb_engine.setCurrentIndex(ids.index("trellis"))
            win.btn_more.setChecked(True)
            audit("vide / plus d'options")
            win.settings_panel.setExpanded(False)
            audit("vide / réglages repliés")
            win.settings_panel.setExpanded(True)
            win.btn_more.setChecked(False)
            # --- image chargée
            win.set_input(test_image())
            QTest.qWait(1000)
            audit("image chargée")
            win.drop.view.setCurrentIndex(1)
            audit("image chargée / détourée")
            win.drop.view.setCurrentIndex(0)
            # --- calcul en cours (tâche qui attend)
            import threading

            gate = threading.Event()
            win.run_task(lambda progress, partial: (progress("Génération du modèle 3D…"), gate.wait(15)) and None,
                         lambda _r: None, kind="generate")
            QTest.qWait(300)
            audit("calcul en cours")
            gate.set()
            wait_idle(win)
            # --- erreur
            win._error = {"kind": "generate", "message": "m", "details": "d"}
            win.error_panel.set_error("La génération a échoué", "Mémoire GPU insuffisante. Choisis une qualité plus basse "
                                      "(Rapide ou Équilibré) et réessaie.", studio.FAILURE_HINT, "détails", True, "Réessayer")
            win._refresh_ui()
            audit("erreur")
            win._error = None
            win._refresh_ui()
            # --- résultat (une variante, puis plusieurs)
            win.cmb_engine.setCurrentIndex(ids.index("triposr"))
            win.on_generate()
            wait_idle(win)
            audit("résultat")
            win.seg_format.setCurrentIndex(studio.FMT_STL)  # la barre d'export avec ses trois formats
            audit("résultat / format STL")
            problems.extend(check_print_dialog(win, f"{w}×{h} · texte {int(scale * 100)} %"))
            win.seg_format.setCurrentIndex(studio.FMT_GLB)
            win.btn_help_toggle = win.viewport.btn_help
            win.viewport.btn_help.setChecked(True)
            audit("résultat / aide des gestes")
            win.viewport.btn_help.setChecked(False)
            for tip in studio.TIPS:  # chaque astuce du robot doit tenir dans sa bulle à cette largeur
                win._tip_override = tip
                win._update_assistant()
                audit("astuce du robot")
            win._tip_override = ""
            win._update_assistant()
            win.cmb_engine.setCurrentIndex(ids.index("trellis"))
            engine.ready = True
            win._update_trellis_install()
            win.spn_variants.setValue(4)
            win.on_generate()
            wait_idle(win, 20)
            win._show_variant(len(win.variants) - 1)
            audit("résultat / variantes")
            win.spn_variants.setValue(1)
            # --- autres pages
            win.tabs.setCurrentIndex(1)
            audit("mes créations")
            win.tabs.setCurrentIndex(2)
            audit("paramètres")
            win.tabs.setCurrentIndex(0)
            # --- remise à zéro pour la taille suivante
            win.set_input(test_image())
            engine.ready = False
            win._update_trellis_install()
            win.spn_variants.setValue(1)
    win.close()
    return problems


if __name__ == "__main__":
    found = run()
    if found:
        print(f"{len(found)} problème(s) de mise en page :")
        for line in found[:200]:
            print(" -", line)
        sys.exit(1)
    print("OK : aucun défaut de mise en page détecté")
