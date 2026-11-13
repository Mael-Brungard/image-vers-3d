"""Test de l'interface avec un moteur factice (pas de torch, pas de GPU).
Lancé avec QT_QPA_PLATFORM=offscreen."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
OUT = Path(os.environ.get("IMAGEVERS3D_TEST_OUT") or tempfile.mkdtemp(prefix="i3d_ui_"))
if "IMAGEVERS3D_DATA" not in os.environ:  # lancé à la main : dossier de données jetable avec une licence de développement
    sys.path.insert(0, str(REPO / "tools"))
    import dev_license

    dev_license.install(Path(tempfile.mkdtemp(prefix="i3d_data_")))

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

# réglages isolés (fichier .ini temporaire) : le test ne lit ni n'écrit ceux de l'utilisateur, ni le registre Windows
_settings_file = str(Path(tempfile.mkdtemp(prefix="i3d_settings_")) / "reglages.ini")


def new_settings():
    return QSettings(_settings_file, QSettings.Format.IniFormat)


from imagevers3d import studio, theme
from imagevers3d.theme import Motion


class FakeEngine:
    def __init__(self, fail=False):
        self.fail = fail
        self.exports = []
        self.sg_ready = False
        self.sg_calls = []
        self.preprocess_white = []

    def triposg_ready(self):
        return self.sg_ready

    def prepare_triposg(self, image, remove_bg, ratio, progress):
        self.preprocess_white.append(True)
        progress("Détourage factice (TripoSG)…")
        time.sleep(0.1)
        rgba = image.convert("RGBA")
        return Image.new("RGB", rgba.size, "white"), rgba

    def generate_triposg(self, prepared, steps, progress, seed=42, cutout=None):
        progress("TripoSG factice…")
        time.sleep(0.15)
        self.sg_calls.append((steps, seed, cutout is not None))
        full = trimesh.creation.icosphere(subdivisions=4)
        full.vertices = full.vertices * [1.6, 0.8, 0.5]  # allongé selon X : doit devenir allongé selon Z après « Pivoter »
        preview = trimesh.creation.icosphere(subdivisions=2)
        preview.vertices = preview.vertices * [1.6, 0.8, 0.5]
        if cutout is not None:  # couleur sRGB (200, 50, 40) partout
            for m in (full, preview):
                c = np.zeros((len(m.vertices), 4), np.uint8); c[:] = (200, 50, 40, 255)
                m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=c)
        full.metadata["file_path"] = r"C:\\Users\\x\\AppData\\Local\\Temp\\mesh.ply"
        return preview, full, ["Remarque factice."]

    def export_triposg(self, result, path, progress):
        return studio.Engine.export_triposg(None, result, path, progress)

    def device_label(self):
        return "GPU : FAKE RTX"

    def preprocess(self, image, remove_bg, ratio, progress):
        self.preprocess_white.append(False)
        progress("Détourage factice…")
        time.sleep(0.15)
        return image.convert("RGB")

    def generate(self, prepared, resolution, progress):
        progress("Génération factice…")
        time.sleep(0.15)
        if self.fail:
            raise RuntimeError("Panne simulée")
        mesh = trimesh.creation.icosphere(subdivisions=3)
        mesh.vertices = mesh.vertices * [1.0, 1.6, 0.8]  # forme allongée
        colors = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
        colors[:, 0] = ((mesh.vertices[:, 0] + 1) * 120).astype(np.uint8)
        colors[:, 1] = ((mesh.vertices[:, 1] + 2) * 60).astype(np.uint8)
        colors[:, 2] = 180
        colors[:, 3] = 255
        mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=colors)
        return mesh, "scene-codes"

    def export(self, mesh, scene_codes, path, bake, progress):
        progress("Export factice…")
        path = Path(path)
        if bake:
            path = path.with_suffix(".obj")
        mesh.copy().export(str(path))
        self.exports.append((path, bake))
        return path


def wait_until(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        QTest.qWait(30)
    return False


def check(label, ok):
    print(("OK   " if ok else "ECHEC"), label)
    if not ok:
        check.failed += 1


check.failed = 0

app = QApplication(sys.argv)
theme.apply_theme(app, "dark")

# Image de test
img = Image.new("RGB", (640, 480), (235, 235, 235))
d = ImageDraw.Draw(img)
d.ellipse((160, 90, 480, 400), fill=(200, 60, 40))
test_png = OUT / "objet_test.png"
img.save(test_png)

# L'interface ne doit ouvrir AUCUNE boîte de dialogue modale pour signaler un problème : on les capte pour le vérifier
dialogs = []
for _name in ("critical", "warning", "information", "question"):
    setattr(QMessageBox, _name, staticmethod(lambda *a, _n=_name, **k: dialogs.append((_n, a[1:]))))
QMessageBox.exec = lambda self: dialogs.append(("box", self.text())) or 0

engine = FakeEngine()
win = studio.MainWindow(engine, new_settings())
win.show()
QTest.qWait(200)

check("fenêtre créée, bouton Enregistrer désactivé au départ", not win.btn_save.isEnabled())
check("état vide au départ (le visualiseur explique quoi faire)", win.viewport.page_name() == "empty")
check("une seule action principale : Générer est le bouton plein, Enregistrer ne l'est pas",
      win.btn_generate.property("kind") == "primary" and win.btn_save.property("kind") in (None, ""))
win.grab().save(str(OUT / "01_vide_sombre.png"))

# 1) Générer sans image : doit seulement afficher un message
win.on_generate()
check("générer sans image ne lance rien", win._task is None and "image" in win.status.text().lower())
check("générer sans image : notification non modale (pas de boîte de dialogue)",
      win.viewport.toast.isVisible() and win.viewport.toast.kind() == "warning" and not dialogs)

# 2) Charger l'image
win.load_path(str(test_png))
check("image chargée", win.input_image is not None and win.input_name == "objet_test")
check("zone de dépôt en mode « chargée »", win.drop.has_image() and win.drop.pixmap() is not None)
win.drop.set_dragging(True)
win.grab().save(str(OUT / "02_depot_survol.png"))
win.drop.set_dragging(False)
win.grab().save(str(OUT / "03_image_chargee.png"))

# 3) Aperçu du détourage
win.on_preview()
check("occupé pendant l'aperçu (boutons désactivés)", not win.btn_generate.isEnabled())
check("aperçu terminé", wait_until(lambda: win._task is None))
check("aperçu affiché (bascule Détourée)", win.drop.has_prepared() and win.drop.shows_prepared())
win.drop.view.setCurrentIndex(0)
check("bascule vers l'image originale", not win.drop.shows_prepared())
win.sld_ratio.setValue(80)
check("changer un réglage de détourage invalide l'aperçu", not win.drop.has_prepared())
win.sld_ratio.setValue(85)
win.drop.view.setCurrentIndex(1)  # demande l'aperçu depuis la bascule
check("la bascule « Détourée » lance l'aperçu", win._task is not None and wait_until(lambda: win._task is None) and win.drop.has_prepared())

# 4) Génération complète
win.on_generate()
QTest.qWait(40)
check("pendant le calcul : page « calcul » et barre de progression", win.viewport.page_name() == "busy" and win.progress.isVisible() and win.progress.isActive())
win.grab().save(str(OUT / "04_calcul.png"))
check("génération terminée", wait_until(lambda: win._task is None and win.result is not None))
check("page résultat, barre de progression arrêtée", win.viewport.page_name() == "result" and not win.progress.isVisible())
check("bouton Enregistrer activé", win.btn_save.isEnabled())
check("l'action principale passe à Enregistrer (Générer devient « Générer à nouveau »)",
      win.btn_save.property("kind") == "primary" and win.btn_generate.property("kind") in (None, "")
      and win.btn_generate.text() == "Générer à nouveau")
check("message de fin affiché", "Modèle prêt" in win.status.text())
check("pastille d'information du modèle", "sommets" in win.viewport.info.text() and "TripoSR" in win.viewport.info.text())
win.btn_wire.setChecked(True)
QTest.qWait(300)
win.btn_wire.setChecked(False)
win.viewer.reset_view()
print("      visionneuse : widget courant =", type(win.viewer.currentWidget()).__name__)

# 5) Enregistrement GLB via le dialogue simulé
tmp = Path(tempfile.mkdtemp())
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "sortie.glb"), ""))
win.seg_format.setCurrentIndex(0)
win.on_save()
check("export terminé", wait_until(lambda: win._task is None and engine.exports))
check("fichier .glb écrit", (tmp / "sortie.glb").exists() and (tmp / "sortie.glb").stat().st_size > 1000)
check("statut « Enregistré »", "Enregistré" in win.status.text())
check("notification de réussite", win.viewport.toast.isVisible() and "sortie.glb" in win.viewport.toast.message())
check("bouton dossier activé", win.btn_folder.isEnabled())

# 6) Texture cuite : l'extension .glb doit devenir .obj
win.seg_format.setCurrentIndex(1)
win.on_save()
check("export avec texture terminé", wait_until(lambda: win._task is None and len(engine.exports) == 2))
check("sortie forcée en .obj", engine.exports[-1][0].suffix == ".obj" and engine.exports[-1][1] is True)

# 7) Capture d'écran de la fenêtre
shot = OUT / "05_resultat_sombre.png"
win.grab().save(str(shot))
print("      capture :", shot)

# 8) Échec du moteur : message d'erreur, interface débloquée
engine.fail = True
win.on_generate()
check("échec géré : panneau d'erreur en ligne, interface débloquée",
      wait_until(lambda: win._task is None) and win.viewport.page_name() == "error" and win.btn_generate.isEnabled())
check("aucune boîte de dialogue modale pour l'erreur", not dialogs)
check("l'erreur dit ce qui s'est passé et garde la trace complète pour le support",
      "Panne simulée" in win.error_panel.message.text() and "Traceback" in win.error_panel.details
      and "génération" in win.error_panel.title.text().lower())
check("l'action principale de la vue d'erreur est « Réessayer »",
      win.error_panel.btn_retry.property("kind") == "primary" and win.btn_generate.property("kind") in (None, ""))
check("« Revenir au modèle » proposé (un résultat existe)", not win.error_panel.btn_back.isHidden())
win.grab().save(str(OUT / "06_erreur_sombre.png"))
win.error_panel.btn_back.click()
check("revenir au modèle ramène le résultat précédent", win.viewport.page_name() == "result" and win.result is not None)
engine.fail = True
win.on_generate()
wait_until(lambda: win._task is None and win.viewport.page_name() == "error")
engine.fail = False
win.error_panel.btn_retry.click()
check("« Réessayer » relance et réussit", wait_until(lambda: win._task is None and win.viewport.page_name() == "result") and win._error is None)
win.error_panel.copyDetails.emit()
check("« Copier les détails » copie la trace", QApplication.clipboard().text() != "")


# 8b) Moteur TripoSG
check("avant TripoSG : réglages TripoSG cachés", win.chk_color.isHidden() and win.seed_row.isHidden())
check("TripoSG absent : seul TripoSR est proposé", win.cmb_engine.count() == 1 and win.cmb_engine.itemData(0) == "triposr")
win.close()
engine.sg_ready = True  # le moteur est maintenant présent sur l'ordinateur : une nouvelle fenêtre le propose
win = studio.MainWindow(engine, new_settings())
win.show()
QTest.qWait(200)
win.load_path(str(test_png))
check("TripoSG présent : proposé en second", win.cmb_engine.count() == 2 and win.cmb_engine.itemData(1) == "triposg" and "installer" not in win.cmb_engine.itemText(1))
win.cmb_quality.setCurrentIndex(1)  # réglage de TripoSR, à retrouver au retour
win.cmb_engine.setCurrentIndex(1)
check("liste de qualités de TripoSG (étapes)", win.cmb_quality.count() == 3 and "étapes" in win.cmb_quality.itemText(1))
check("options : moteur et étapes", win.options().engine == "triposg" and win.options().resolution == 50)
check("réglages TripoSG visibles (couleurs, variante)", not win.chk_color.isHidden() and not win.seed_row.isHidden() and win.options().colorize and win.options().seed == 42)
win.on_generate()
check("TripoSG : génération terminée", wait_until(lambda: win._task is None and win.result is not None and win.result["engine"] == "triposg"))
check("TripoSG : préparation spécifique (fond blanc)", engine.preprocess_white and engine.preprocess_white[-1] is True)
check("TripoSG : 50 étapes, variante 42, image envoyée pour les couleurs", engine.sg_calls == [(50, 42, True)])
check("TripoSG : la remarque du moteur est affichée dans le statut", "Remarque factice." in win.status.text())
check("TripoSG : OBJ avec texture indisponible, boutons de rotation visibles",
      not win.seg_format.isItemEnabled(1) and not win.btn_turn.isHidden() and not win.btn_flip.isHidden())
check("TripoSG : boutons de rotation et d'enregistrement actifs", win.btn_turn.isEnabled() and win.btn_flip.isEnabled() and win.btn_save.isEnabled())
full_count = f"{len(win.result['mesh_export'].vertices):,}".replace(",", " ")
check("TripoSG : le statut donne le nombre de sommets du maillage complet", full_count in win.status.text())
win.grab().save(str(OUT / "fenetre_triposg.png"))

win.on_rotate("turn")
check("pivoter : la matrice de correction change", not np.allclose(win.result["extra"], np.eye(3)))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "sg_modele.glb"), ""))
win.on_save()
check("TripoSG : export terminé", wait_until(lambda: win._task is None and (tmp / "sg_modele.glb").exists()))
exported = trimesh.load(str(tmp / "sg_modele.glb"), force="mesh")
extent = exported.bounds[1] - exported.bounds[0]
check("TripoSG : export complet (maillage complet, pas l'aperçu)", len(exported.vertices) >= len(win.result["mesh_export"].vertices) * 0.99)
check("pivoter : l'objet allongé selon X l'est maintenant selon Z dans le fichier", extent[2] > extent[0] * 1.5 and extent[2] > extent[1] * 1.5)
import json, struct
raw = (tmp / "sg_modele.glb").read_bytes()
jl = struct.unpack("<I", raw[12:16])[0]
gj = json.loads(raw[20:20 + jl])
attrs = set(gj["meshes"][0]["primitives"][0]["attributes"])
check("TripoSG : le GLB contient normales et couleurs", {"NORMAL", "POSITION", "COLOR_0"} <= attrs)
check("TripoSG : aucun chemin local dans le GLB", b"AppData" not in raw and b"Users" not in raw)

before = win.result["extra"].copy()
win.on_rotate("flip")
check("redresser : la matrice change", not np.allclose(before, win.result["extra"]))
for _ in range(3):
    win.on_rotate("flip")
check("redresser x4 : retour à l'orientation d'avant", np.allclose(before, win.result["extra"]))

win.cmb_engine.setCurrentIndex(0)
check("retour sur TripoSR : liste d'origine et réglage mémorisé retrouvé", win.cmb_quality.count() == 4 and win.cmb_quality.currentIndex() == 1)
check("résultat TripoSG affiché : l'export reste sans texture cuite", not win.seg_format.isItemEnabled(1) and not win.btn_turn.isHidden())

# 8c) Thèmes, taille du texte, mouvement réduit
win.grab().save(str(OUT / "07_triposg_sombre.png"))
win._set_theme("light")
QTest.qWait(50)
check("thème clair appliqué", theme.current().mode == "light" and theme.current()["bg-app"] == "#F4F5F7")
win.grab().save(str(OUT / "08_resultat_clair.png"))
win._set_scale(1.3)
QTest.qWait(50)
check("texte à 130 % : le panneau s'élargit", win._left.width() == theme.current().px(392) and theme.current().scale == 1.3)
win.grab().save(str(OUT / "09_texte_130.png"))
win._set_scale(1.0)
win._set_reduce_motion(True)
check("« Réduire les animations » coupe le mouvement", not Motion.enabled())
win.cmb_quality.setCurrentIndex(0)
check("sans animation, le contrôle segmenté saute directement à la valeur", win.cmb_quality._pos == 0.0)
win._set_reduce_motion(False)
win._set_theme("system")
check("thème « Système » : se résout en sombre ou clair", theme.current().mode in ("dark", "light") and win.theme_pref == "system")
win._set_theme("dark")
win._open_menu()
QTest.qWait(80)
check("menu Réglages et aide ouvert", win.menu.isVisible())
win.menu.grab().save(str(OUT / "10_menu.png"))
win.menu.close()
win.cmb_quality.setCurrentIndex(1)

# 8d) Accessibilité : chaque bouton icône a un nom, rien ne vole le focus à la souris
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QToolButton
unnamed = [b.objectName() for b in win.findChildren(QToolButton) if not b.accessibleName()]
check("tous les boutons icône ont un nom accessible", not unnamed)
check("boutons : focus visible au clavier seulement (pas d'anneau au clic)",
      all(b.focusPolicy() == Qt.FocusPolicy.TabFocus for b in win.findChildren(QPushButton) + win.findChildren(QToolButton)))
check("aucune boîte de dialogue modale n'a été ouverte pendant tout le test", not dialogs)

# 9) Réglages mémorisés
win.sld_ratio.setValue(70)
win.cmb_quality.setCurrentIndex(3)
win.close()
check("options lues", win.options().ratio == 0.7 and win.options().resolution == 320)

print("\nRésultat :", "tout est OK" if check.failed == 0 else f"{check.failed} échec(s)")
sys.exit(1 if check.failed else 0)
