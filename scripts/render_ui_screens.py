"""Enregistre des captures de l'interface (rendu hors écran, moteur factice) pour le README et la documentation.

    python scripts/render_ui_screens.py docs/images

États : écran vide, image chargée, calcul en cours, erreur, « Mes créations », « Paramètres ».
Le visualiseur 3D (OpenGL) n'existe pas en rendu hors écran : il reste vide dans ces captures.
"""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("THREEREX_DATA", tempfile.mkdtemp(prefix="trx_data_"))
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from threerex import fx, studio  # noqa: E402
from threerex.creations import CreationStore  # noqa: E402

fx.Clock.require_active = False  # la plateforme hors écran ne devient pas « active » : on anime quand même


class DemoEngine:
    """Moteur factice : l'interface se rend sans PyTorch ni GPU ; la génération échoue exprès pour montrer l'erreur."""

    def triposg_ready(self):
        return False

    def trellis_supported(self):
        return False

    def trellis_ready(self):
        return False

    def trellis_quant(self):
        return "q4"

    def set_trellis_quant(self, quant):
        pass

    def device_label(self):
        return "GPU : NVIDIA GeForce RTX 4070 Ti"

    def preprocess(self, image, remove_bg, ratio, progress):
        progress("Détourage de l'image…")
        time.sleep(0.05)
        return image.convert("RGB")

    def generate(self, prepared, resolution, progress):
        raise RuntimeError("Mémoire GPU insuffisante. Choisis une qualité plus basse (Rapide ou Équilibré) et réessaie.")


def demo_image() -> Image.Image:
    """Un vase orange sur fond clair : un sujet simple, comme celui que le logiciel reconstruit le mieux."""
    img = Image.new("RGB", (900, 700), (236, 232, 226))
    d = ImageDraw.Draw(img)
    d.ellipse((260, 90, 640, 170), fill=(150, 70, 40))
    d.polygon([(300, 130), (600, 130), (700, 420), (560, 640), (340, 640), (200, 420)], fill=(190, 92, 52))
    d.ellipse((330, 70, 570, 150), fill=(110, 50, 30))
    return img.filter(ImageFilter.GaussianBlur(1.2)).convert("RGBA")


def window(app, store_dir: Path) -> studio.MainWindow:
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "reglages.ini"), QSettings.Format.IniFormat)
    store = CreationStore(store_dir)
    win = studio.MainWindow(DemoEngine(), settings, store)
    win.resize(1360, 880)
    win.show()
    QTest.qWait(300)
    return win


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    store_dir = Path(tempfile.mkdtemp(prefix="trx_creations_"))
    models = Path(tempfile.mkdtemp(prefix="trx_models_"))
    store = CreationStore(store_dir)
    for name, engine, info in (("vase_orange.glb", "TRELLIS.2", "1024 · 412 380 sommets"),
                               ("lampe_de_bureau.glb", "TripoSR", "256 · 38 910 sommets"),
                               ("statuette.obj", "TRELLIS.2", "1024 · 506 114 sommets")):
        model = models / name
        model.write_bytes(b"x" * 400_000)
        store.add(model, engine=engine, info=info, thumbnail=demo_image())

    win = window(app, store_dir)

    def shot(name: str) -> None:
        QTest.qWait(300)
        win.grab().save(str(out / f"{name}.png"))

    shot("ecran-vide")
    win.set_input(demo_image())
    QTest.qWait(1200)
    shot("ecran-image-chargee")

    gate = threading.Event()

    def waiting(progress, partial):
        progress("Génération du modèle 3D…")
        gate.wait(20)

    win.run_task(waiting, lambda _result: None, kind="generate")
    QTest.qWait(1600)
    shot("ecran-calcul")
    gate.set()
    end = time.time() + 10
    while win._task is not None and time.time() < end:
        QTest.qWait(30)

    win.on_generate()
    end = time.time() + 10
    while win._task is not None and time.time() < end:
        QTest.qWait(30)
    shot("ecran-erreur")

    win.tabs.setCurrentIndex(studio.TAB_CREATIONS)
    shot("ecran-creations")
    win.tabs.setCurrentIndex(studio.TAB_SETTINGS)
    shot("ecran-parametres")
    win.close()
    print("captures écrites dans", out)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/images"))
