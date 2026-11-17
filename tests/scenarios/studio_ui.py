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
OUT = Path(os.environ.get("THREEREX_TEST_OUT") or tempfile.mkdtemp(prefix="i3d_ui_"))
os.environ.setdefault("THREEREX_DATA", str(Path(tempfile.mkdtemp(prefix="i3d_data_"))))

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

# réglages isolés (fichier .ini temporaire) : le test ne lit ni n'écrit ceux de l'utilisateur, ni le registre Windows
_settings_file = str(Path(tempfile.mkdtemp(prefix="i3d_settings_")) / "reglages.ini")


def new_settings():
    return QSettings(_settings_file, QSettings.Format.IniFormat)


from threerex import printing, studio, theme
from threerex.theme import Motion

# Un serveur Windows a souvent « Afficher les animations » coupé : le scénario ne doit pas dépendre du réglage de la machine.
theme.system_prefers_reduced_motion = lambda: False


class StubPrintDialog:
    """Remplace la fenêtre « Impression 3D » (elle bloquerait le test) : mêmes arguments, réponse programmée."""

    seen = []
    accept = True
    height = 80

    def __init__(self, parent, ratios, options):
        StubPrintDialog.seen.append((ratios, options))

    def exec(self):
        return 1 if StubPrintDialog.accept else 0

    def values(self):
        return printing.PrintOptions(height_mm=StubPrintDialog.height, flatten=True)


class FakeEngine:
    def __init__(self, fail=False):
        self.fail = fail
        self.exports = []
        self.sg_ready = False
        self.sg_calls = []
        self.tr_supported = False
        self.tr_ready = False
        self.tr_calls = []
        self.tr_previews = []
        self.tr_installs = 0
        self.tr_quant = "q4"
        self.tr_fail_seed = None  # numéro de variante dont le calcul échoue
        self.preprocess_white = []

    def triposg_ready(self):
        return self.sg_ready

    def trellis_supported(self):
        return self.tr_supported

    def trellis_ready(self):
        return self.tr_ready

    def trellis_download_size(self):
        return 7_200_000_000 if self.tr_quant == "q4" else 10_700_000_000

    def trellis_quant(self):
        return self.tr_quant

    def set_trellis_quant(self, quant):
        self.tr_quant = quant

    def install_trellis(self, progress):
        progress("Téléchargement factice du moteur…")
        time.sleep(0.2)
        self.tr_installs += 1
        self.tr_ready = True

    def prepare_trellis(self, image, remove_bg, ratio, progress):
        progress("Détourage factice (TRELLIS.2)…")
        time.sleep(0.1)
        self.tr_previews.append(remove_bg)
        return Image.new("RGB", image.size, "white")

    def generate_trellis(self, image, quality, remove_bg, seed, progress, texture="standard"):
        progress("TRELLIS.2 factice…")
        time.sleep(0.15)
        if seed == self.tr_fail_seed:
            raise RuntimeError("Panne de la variante factice\nDétail technique")
        self.tr_calls.append((quality, remove_bg, seed, texture))
        box = trimesh.creation.box(extents=(1.0, 2.0, 3.0))
        uv = box.vertices[:, :2] * 0.0 + 0.5
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new("RGB", (8, 8), (30, 90, 200)))
        box.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
        glb = bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(box)))
        preview = trimesh.creation.icosphere(subdivisions=3)
        c = np.zeros((len(preview.vertices), 4), np.uint8); c[:] = (30, 90, 200, 255)
        preview.visual = trimesh.visual.ColorVisuals(preview, vertex_colors=c)
        return {"glb": glb, "mesh": preview, "notes": ["Note factice TRELLIS."], "res": 1024, "fine": texture == "fine"}

    def export_trellis(self, result, path, progress):
        return studio.Engine.export_trellis(None, result, path, progress)

    def export_print(self, result, path, options, progress):
        return studio.Engine.export_print(None, result, path, options, progress)

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


def fx_clock_static():
    from threerex import fx

    return fx.Clock.t(True) == 0.0

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
check("pendant le calcul : moteur, qualité et réglages figés (lus au lancement)",
      not any(w.isEnabled() for w in (win.cmb_engine, win.cmb_quality, win.chk_bg, win.sld_ratio, win.spn_seed)))
win.grab().save(str(OUT / "04_calcul.png"))
check("génération terminée", wait_until(lambda: win._task is None and win.result is not None))
check("après le calcul : réglages de nouveau modifiables",
      all(w.isEnabled() for w in (win.cmb_engine, win.cmb_quality, win.chk_bg, win.sld_ratio, win.spn_seed)))
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
saved_items = win.store.load()
check("« Mes créations » retient le fichier enregistré (moteur, nom, vignette)",
      len(saved_items) == 1 and saved_items[0].name == "sortie.glb" and saved_items[0].engine == "TripoSR"
      and win.store.thumb_path(saved_items[0]) is not None)
win.tabs.setCurrentIndex(1)
QTest.qWait(60)
check("onglet « Mes créations » : une carte, avec ses boutons",
      win.pages.currentIndex() == 1 and len(win.creations_page.cards) == 1 and win.creations_page.cards[0].btn_open.isEnabled())
win.grab().save(str(OUT / "06_mes_creations.png"))
win.creations_page.cards[0].btn_remove.click()
check("retirer une carte ne supprime jamais le fichier", not win.creations_page.cards and (tmp / "sortie.glb").exists()
      and not win.store.load())
win.tabs.setCurrentIndex(0)
check("retour à l'onglet principal", win.pages.currentIndex() == 0 and win.viewport.page_name() == "result")

# 6) Texture cuite : l'extension .glb doit devenir .obj
win.seg_format.setCurrentIndex(1)
win.on_save()
check("export avec texture terminé", wait_until(lambda: win._task is None and len(engine.exports) == 2))
check("sortie forcée en .obj", engine.exports[-1][0].suffix == ".obj" and engine.exports[-1][1] is True)

# 6b) Impression 3D : format STL, fenêtre de réglage, surface réparée, mise à l'échelle, rapport honnête
studio.PrintDialog = StubPrintDialog
check("format STL proposé en troisième choix, avec TripoSR", win.seg_format.count() == 3 and win.seg_format.isItemEnabled(2)
      and win.seg_format.itemData(2) == "stl")
win.seg_format.setCurrentIndex(2)
asked_stl = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (asked_stl.append(a[2]) or str(tmp / "figurine"), ""))  # sans extension
StubPrintDialog.accept = False
win.on_save()
check("fenêtre « Impression 3D » annulée : ni sélecteur de fichier, ni export", not asked_stl and win._task is None)
StubPrintDialog.accept = True
win.on_save()
check("STL : export terminé, extension .stl ajoutée", wait_until(lambda: win._task is None and (tmp / "figurine.stl").exists()))
check("STL : nom proposé en .stl", asked_stl and asked_stl[0].endswith(".stl"))
ratios, shown_options = StubPrintDialog.seen[0]
check("STL : la fenêtre reçoit les proportions du modèle et les réglages par défaut (150 mm, dessous aplati)",
      ratios is not None and len(ratios) == 2 and all(r > 0 for r in ratios)
      and shown_options.height_mm == printing.DEFAULT_HEIGHT_MM and shown_options.flatten)
stl_mesh = trimesh.load(str(tmp / "figurine.stl"))
check("STL : surface fermée, posée sur le plateau, hauteur demandée (80 mm)",
      stl_mesh.is_watertight and abs(stl_mesh.bounds[0][2]) < 1e-3 and abs(stl_mesh.bounds[1][2] - 80) < 1e-2)
ratio = np.sort(stl_mesh.extents) / 80.0  # icosphère étirée 2 × 3,2 × 1,6 (hauteur 1,6), dessous aplati : 1 ; 1,27 ; 2,03
check("STL : proportions du modèle conservées", np.allclose(ratio, [1.0, 1.27, 2.03], rtol=0.03))
check("STL : la barre d'état et la notification donnent le rapport (surface fermée, taille)",
      "Enregistré" in win.status.text() and "surface fermée" in win.status.text() and "80 mm" in win.status.text()
      and win.viewport.toast.kind() == "success" and "figurine.stl" in win.viewport.toast.message())
check("STL : le réglage choisi est retenu pour la prochaine fois", win._print.height_mm == 80)
check("STL : le fichier rejoint « Mes créations »", any(c.name == "figurine.stl" for c in win.store.load()))
# une surface qu'on ne peut pas réparer : fichier écrit, avertissement SANS boîte de dialogue modale
cube = trimesh.creation.box(extents=(1, 1, 1))
wing = [[cube.edges_unique[0][0], cube.edges_unique[0][1], len(cube.vertices)]]
unfixable = trimesh.Trimesh(np.vstack([cube.vertices, [[0.5, 0.5, 2.0]]]), np.vstack([cube.faces, wing]), process=False)
good_result = win.result
win.result = {**good_result, "mesh": unfixable}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "abime.stl"), ""))
win.on_save()
check("STL non réparable : fichier tout de même écrit", wait_until(lambda: win._task is None and (tmp / "abime.stl").exists()))
check("STL non réparable : avertissement dans le toast, la barre d'état et la bulle du robot, sans boîte modale",
      win.viewport.toast.kind() == "warning" and "NON étanche" in win.status.text()
      and win._assistant_text() == studio.STL_OPEN_HINT and not dialogs)
win.result = good_result
win.seg_format.setCurrentIndex(0)  # on rend la main aux scénarios suivants : GLB
# réglages mémorisés : format et hauteur ; anciens réglages (« bake ») relus
probe_file = str(Path(tempfile.mkdtemp(prefix="i3d_probe_")) / "p.ini")
probe = QSettings(probe_file, QSettings.Format.IniFormat)
first = studio.MainWindow(FakeEngine(), probe)
first.seg_format.setCurrentIndex(2)
first._print = printing.PrintOptions(65, False)
first.close()
second = studio.MainWindow(FakeEngine(), QSettings(probe_file, QSettings.Format.IniFormat))
check("format STL, hauteur et aplatissement mémorisés d'une session à l'autre",
      second.seg_format.currentIndex() == 2 and second._print.height_mm == 65 and not second._print.flatten)
second.close()
legacy_file = str(Path(tempfile.mkdtemp(prefix="i3d_legacy_")) / "l.ini")
legacy = QSettings(legacy_file, QSettings.Format.IniFormat)
legacy.setValue("bake", True)
legacy.sync()
third = studio.MainWindow(FakeEngine(), QSettings(legacy_file, QSettings.Format.IniFormat))
check("anciens réglages : « OBJ avec texture » (clé « bake ») est retrouvé", third.seg_format.currentIndex() == 1)
third.close()

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

# 8b-bis) Moteur TRELLIS.2 (« Qualité maximale ») : à installer, puis génération et export
engine.tr_supported = True
wt = studio.MainWindow(engine, new_settings())
wt.show()
QTest.qWait(200)
wt.load_path(str(test_png))
ids = [wt.cmb_engine.itemData(i) for i in range(wt.cmb_engine.count())]
check("TRELLIS.2 proposé entre TripoSR et TripoSG", ids == ["triposr", "trellis", "triposg"])
check("pas encore installé : TripoSR reste le moteur par défaut", wt._engine_id() == "triposr" and wt.btn_install_engine.isHidden())
wt.cmb_engine.setCurrentIndex(1)
check("TRELLIS.2 non installé : bouton d'installation avec la taille, explication visible",
      not wt.btn_install_engine.isHidden() and "7,2 Go" in wt.btn_install_engine.text() and not wt.lbl_engine_note.isHidden()
      and "une seule fois" in wt.lbl_engine_note.text())
check("TRELLIS.2 : qualités Rapide / Détaillé / Maximum / Ultra, Détaillé par défaut",
      wt.cmb_quality.count() == 4 and wt.cmb_quality.itemText(3).startswith("Ultra") and wt.options().resolution == "detaille" and wt.options().engine == "trellis")
check("TRELLIS.2 : variante visible, taille de l'objet et colorisation cachées",
      not wt.seed_row.isHidden() and wt.chk_color.isHidden() and wt.sld_ratio.isHidden() and wt.lbl_ratio_title.isHidden())
QTest.qWait(100)
wt.grab().save(str(OUT / "11_trellis_a_installer.png"))
wt.on_generate()
check("générer sans le moteur : message, aucune tâche", wt._task is None and wt.viewport.toast.isVisible() and not engine.tr_calls)
wt.on_install_engine()
check("installation : page de travail et titre dédié",
      wt._task is not None and wt.viewport.page_name() == "busy" and "Installation" in wt.viewport.busy.title.text())
check("installation : bouton d'installation et choix du moteur figés", not wt.btn_install_engine.isEnabled() and not wt.cmb_engine.isEnabled())
check("installation terminée : bouton remplacé par l'explication « prêt »",
      wait_until(lambda: wt._task is None and engine.tr_ready) and wt.btn_install_engine.isHidden()
      and "Textures PBR" in wt.lbl_engine_note.text() and engine.tr_installs == 1)
wt.on_preview()
check("TRELLIS.2 : aperçu du détourage par le moteur", wait_until(lambda: wt._task is None) and engine.tr_previews == [True] and wt.drop.has_prepared())
wt.spn_seed.setValue(5)
wt.on_generate()
check("TRELLIS.2 : génération terminée", wait_until(lambda: wt._task is None and wt.result is not None and wt.result["engine"] == "trellis"))
check("TRELLIS.2 : qualité, détourage et variante transmis", engine.tr_calls == [("detaille", True, 5, "standard")])
check("TRELLIS.2 : remarque du moteur dans le statut, moteur nommé dans la pastille",
      "Note factice TRELLIS." in wt.status.text() and "TRELLIS.2" in wt.viewport.info.text())
check("TRELLIS.2 : OBJ avec texture permis, rotations visibles, enregistrement actif",
      wt.seg_format.isItemEnabled(1) and not wt.btn_turn.isHidden() and wt.btn_save.isEnabled())
QTest.qWait(100)
wt.grab().save(str(OUT / "12_trellis_resultat.png"))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "tr_modele.glb"), ""))
wt.on_save()
check("TRELLIS.2 : export GLB terminé, octets du moteur conservés (texture PBR intacte)",
      wait_until(lambda: wt._task is None and (tmp / "tr_modele.glb").exists()) and (tmp / "tr_modele.glb").read_bytes() == wt.result["glb"])
wt.on_rotate("turn")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "tr_pivote.glb"), ""))
wt.on_save()
check("TRELLIS.2 : après « Pivoter », l'export est tourné et garde sa texture", wait_until(lambda: wt._task is None and (tmp / "tr_pivote.glb").exists()))
turned = trimesh.load(str(tmp / "tr_pivote.glb"), force="mesh")
check("TRELLIS.2 : le quart de tour est dans le fichier, la texture aussi",
      np.allclose(turned.extents, [3, 2, 1], atol=1e-4) and turned.visual.kind == "texture")
wt.seg_format.setCurrentIndex(1)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "tr_modele.obj"), ""))
wt.on_save()
check("TRELLIS.2 : « OBJ avec texture » écrit un .obj et sa texture", wait_until(lambda: wt._task is None and (tmp / "tr_modele.obj").exists()) and list(tmp.glob("*.mtl")))
# --- impression 3D avec TRELLIS.2 : le .glb du moteur est réparé ; le quart de tour fait à la main est pris en compte
wt.seg_format.setCurrentIndex(2)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "tr_figurine.stl"), ""))
wt.on_save()
check("TRELLIS.2 : STL écrit à partir du .glb du moteur", wait_until(lambda: wt._task is None and (tmp / "tr_figurine.stl").exists()))
check("TRELLIS.2 : la fenêtre se souvient de la hauteur déjà choisie", StubPrintDialog.seen[-1][1].height_mm == 80)
tr_stl = trimesh.load(str(tmp / "tr_figurine.stl"))
# boîte 1 × 2 × 3 pivotée (3 × 2 × 1), hauteur 80 mm : échelle 40 → 120 × 80 × 40 ; fond plat : rien n'est coupé
check("TRELLIS.2 : STL fermé, 80 mm de haut, quart de tour pris en compte, fond plat conservé",
      tr_stl.is_watertight and np.allclose(np.sort(tr_stl.extents), [40, 80, 120], atol=0.01)
      and abs(tr_stl.bounds[0][2]) < 1e-3 and abs(tr_stl.bounds[1][2] - 80) < 1e-3
      and abs(tr_stl.volume - 40 * 80 * 120) < 1.0)
wt.seg_format.setCurrentIndex(0)
check("retour au format GLB pour la suite", wt.seg_format.currentIndex() == 0 and wt._format_pref == 0)
# --- meilleur résultat : précision, texture très fine, variantes multiples
check("TRELLIS.2 : précision (Standard par défaut), texture très fine et nombre de variantes proposés",
      not wt.precision_row.isHidden() and wt.cmb_precision.currentData() == "q4" and not wt.chk_texture.isHidden()
      and not wt.variants_row.isHidden() and wt.spn_variants.value() == 1 and not wt.chk_texture.isChecked())
check("un seul résultat : pas de sélecteur de variante", wt.viewport.variant_bar.isHidden())
wt.cmb_precision.setCurrentIndex(1)
check("précision Haute : le moteur change de poids et la taille à télécharger suit", engine.tr_quant == "q8" and engine.trellis_download_size() > 10e9)
wt.cmb_precision.setCurrentIndex(0)
check("retour à la précision Standard", engine.tr_quant == "q4")
wt.chk_texture.setChecked(True)
wt.spn_variants.setValue(3)
wt.spn_seed.setValue(5)
check("options : texture fine et 3 variantes", wt.options().texture == "fine" and wt.options().variants == 3)
engine.tr_calls.clear()
wt.on_generate()
QTest.qWait(60)
check("pendant le calcul : précision, texture et variantes figées",
      not any(w.isEnabled() for w in (wt.cmb_precision, wt.chk_texture, wt.spn_variants)))
check("trois variantes générées à la suite (numéros 5, 6, 7), texture fine transmise",
      wait_until(lambda: wt._task is None and len(wt.variants) == 3)
      and engine.tr_calls == [("detaille", True, 5, "fine"), ("detaille", True, 6, "fine"), ("detaille", True, 7, "fine")])
check("sélecteur de variante affiché avec 3 choix, première variante montrée",
      not wt.viewport.variant_bar.isHidden() and wt.seg_variant.count() == 3 and wt.seg_variant.currentIndex() == 0
      and wt.result is wt.variants[0] and "variante 1/3" in wt.viewport.info.text())
QTest.qWait(100)
wt.grab().save(str(OUT / "13_trellis_variantes.png"))
wt.seg_variant.setCurrentIndex(1)
check("choisir la variante 2 : modèle, pastille et état suivent",
      wt.result is wt.variants[1] and "variante 2/3" in wt.viewport.info.text() and "Variante 2 sur 3 (numéro 6)" in wt.status.text())
before = [v["extra"].copy() for v in wt.variants]
wt.on_rotate("turn")
check("« Pivoter » vaut pour toutes les variantes", all(not np.allclose(v["extra"], b) for v, b in zip(wt.variants, before)))
asked = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (asked.append(a[2]) or str(tmp / "var2.glb"), ""))
wt.on_save()
check("enregistrer : nom proposé avec le numéro de variante, export de la variante choisie",
      wait_until(lambda: wt._task is None and (tmp / "var2.glb").exists()) and Path(asked[0]).stem.endswith("_v2")
      and np.allclose(trimesh.load(str(tmp / "var2.glb"), force="mesh").extents, [3, 2, 1], atol=1e-4))  # variante pivotée
engine.tr_fail_seed, engine.tr_calls[:] = 6, []
wt.on_generate()
check("la variante 2 échoue : la variante 1 est gardée et le problème est signalé",
      wait_until(lambda: wt._task is None and wt.result is not None) and len(wt.variants) == 1 and wt.viewport.variant_bar.isHidden()
      and "La variante 2 n'a pas abouti : Panne de la variante factice" in wt.status.text())
engine.tr_fail_seed = 5
wt.on_generate()
check("la première variante échoue : erreur normale, aucune variante partielle",
      wait_until(lambda: wt._task is None and wt._error is not None) and wt.viewport.page_name() == "error")
engine.tr_fail_seed = None
wt._on_retry()
check("réessayer après l'erreur : variantes de nouveau générées", wait_until(lambda: wt._task is None and len(wt.variants) == 3))
wt.set_input(Image.new("RGB", (64, 64), "white"))
check("nouvelle image : variantes et sélecteur remis à zéro", wt.variants == [] and wt.viewport.variant_bar.isHidden() and wt.result is None)
check("image petite : conseil non bloquant affiché, l'image est quand même chargée",
      wt.viewport.toast.isVisible() and "Conseil" in wt.viewport.toast.message() and "petite" in wt.viewport.toast.message()
      and wt.input_image is not None and wt._error is None)

cancelled = []
real_cancel = studio.cancel_trellis
studio.cancel_trellis = lambda: cancelled.append(True)
wt.close()
studio.cancel_trellis = real_cancel
check("fermer la fenêtre arrête téléchargement et calcul TRELLIS.2 (carte graphique libérée)", cancelled == [True])
engine.tr_quant = "q4"
saved = new_settings()
saved.setValue("trellis_quant", "q8")
again = studio.MainWindow(engine, saved)
check("réglages de qualité mémorisés : texture fine, 3 variantes, précision Haute",
      again.chk_texture.isChecked() and again.spn_variants.value() == 3 and again.cmb_precision.currentData() == "q8"
      and engine.tr_quant == "q8")
again.close()
engine.tr_quant = "q4"
engine.tr_supported = False

# 8b-ter) Vrai Engine : TRELLIS.2 libère la mémoire vidéo de TripoSR et n'est offert qu'avec un pilote NVIDIA
from threerex.trellis_runner import TrellisRunner  # noqa: E402

real = studio.Engine()
real.trellis = TrellisRunner(base=tmp / "tr_a", windows=True, nvidia=False)
check("sans pilote NVIDIA : moteur non proposé", not real.trellis_supported())
real.trellis = TrellisRunner(base=tmp / "tr_b", windows=True, nvidia=True)
check("avec pilote NVIDIA sous Windows : moteur proposé", real.trellis_supported())


class _Runner:
    def generate(self, *a):
        return {"glb": b"", "mesh": None, "notes": [], "res": 512}

    def cutout(self, *a):
        return None


real.trellis, real.model = _Runner(), object()
real.generate_trellis(Image.new("RGB", (8, 8)), "rapide", True, 1, lambda m: None)
check("générer avec TRELLIS.2 libère d'abord le modèle TripoSR", real.model is None)
real.model = object()
real.prepare_trellis = studio.Engine.prepare_trellis.__get__(real)
real.prepare_triposg = lambda *a: (Image.new("RGB", (8, 8)),)
real.prepare_trellis(Image.new("RGB", (8, 8)), True, 0.85, lambda m: None)
check("l'aperçu du détourage TRELLIS.2 libère aussi le modèle TripoSR", real.model is None)

# 8b-ter bis) Réglages de l'ancien nom du logiciel repris une seule fois
old_ini, new_ini = tmp / "ancien.ini", tmp / "nouveau.ini"
legacy = QSettings(str(old_ini), QSettings.Format.IniFormat)
legacy.setValue("seed", 77)
legacy.sync()
fresh = QSettings(str(new_ini), QSettings.Format.IniFormat)
check("réglages de l'ancien nom repris dans un fichier neuf", studio.migrate_legacy_settings(fresh, legacy) and fresh.value("seed", type=int) == 77)
fresh.setValue("seed", 5)
check("ils ne réécrasent jamais des réglages existants", not studio.migrate_legacy_settings(fresh, legacy) and fresh.value("seed", type=int) == 5)

# 8b-quater) Page Paramètres : copier le prompt pour créer l'image
from PySide6.QtGui import QGuiApplication  # noqa: E402

QGuiApplication.clipboard().setText("avant")
win.tabs.setCurrentIndex(2)
QTest.qWait(50)
check("onglet « Paramètres » affiché", win.pages.currentIndex() == 2 and win.settings_page.isVisible())
win.grab().save(str(OUT / "10_parametres.png"))
win.settings_page.btn_prompt.click()
check("Paramètres : « Copier le prompt » met le texte dans le presse-papiers et prévient",
      "[DÉCRIS ICI" in QGuiApplication.clipboard().text() and "Prompt copié" in win.viewport.toast.message())
check("copier le prompt ramène à l'onglet principal", win.pages.currentIndex() == 0)

# 8c) Taille du texte, mouvement réduit, effets visuels
win.grab().save(str(OUT / "07_triposg_sombre.png"))
check("un seul thème : sombre", theme.current().mode == "dark" and theme.current()["bg-app"] == "#0C0A18")
win.settings_page.seg_scale.setCurrentIndex(2)
QTest.qWait(50)
check("texte à 130 % : tout est mis à l'échelle, la fenêtre ne rétrécit pas sous sa taille minimale",
      theme.current().scale == 1.3 and win.minimumWidth() == theme.current().px(1000)
      and win._left.minimumWidth() == theme.current().px(340))
win.grab().save(str(OUT / "09_texte_130.png"))
win.settings_page.seg_scale.setCurrentIndex(0)
win._set_reduce_motion(True)
check("« Réduire les animations » coupe le mouvement", not Motion.enabled() and not Motion.ambient())
win.cmb_quality.setCurrentIndex(0)
check("sans animation, le contrôle segmenté saute directement à la valeur", win.cmb_quality._pos == 0.0)
win._set_reduce_motion(False)
check("mouvement rétabli", Motion.enabled() and Motion.ambient())
win.settings_page.sw_effects.setChecked(False)
check("« Effets visuels » coupés : décor immobile, les gestes restent animés",
      not Motion.ambient() and Motion.enabled() and fx_clock_static())
win.settings_page.sw_effects.setChecked(True)
check("effets visuels rétablis", Motion.ambient())
win.cmb_quality.setCurrentIndex(1)

# 8c-bis) Plein écran du visualiseur, onglets au clavier, assistant et pastilles du pied de page
win.toggle_fullscreen()
check("plein écran : l'interface s'efface autour du visualiseur",
      win.isFullScreen() and not win._left.isVisible() and not win._topbar.isVisible() and not win._footer.isVisible()
      and win.viewport.isVisible())
win.toggle_fullscreen()
QTest.qWait(50)
check("on revient à l'interface complète", not win.isFullScreen() and win._left.isVisible() and win._topbar.isVisible()
      and win._footer.isVisible())
QTest.keyClick(win, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
check("Ctrl+2 ouvre « Mes créations »", win.pages.currentIndex() == 1)
QTest.keyClick(win, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
check("Ctrl+1 revient à l'onglet principal", win.pages.currentIndex() == 0)
check("pastilles du pied de page : image, moteur (données réelles, rien d'inventé)",
      win.pill_image.text().startswith("Image : ") and win.pill_engine.text().startswith("Moteur : "))
check("durée de la dernière génération mesurée, pas estimée",
      win.pill_time.text().startswith("Dernière génération : ") and win._last_duration is not None)
check("l'assistant commente l'état courant", "modèle" in win.bubble.text().lower() or "tourne" in win.bubble.text().lower())
before = win.bubble.text()
win.robot.clicked.emit()
check("un clic sur le robot donne une astuce", win.bubble.text() != before and win.bubble.text() in studio.TIPS)
check("les conseils du robot tiennent dans sa bulle (jamais coupés)", not win.bubble.is_elided())

# 8d) Accessibilité : chaque bouton icône a un nom, rien ne vole le focus à la souris
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
