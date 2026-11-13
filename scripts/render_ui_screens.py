"""Enregistre des captures de l'interface (rendu hors écran, moteur factice) : états vide, image chargée, erreur.

    python scripts/render_ui_screens.py docs/images

Le visualiseur 3D (OpenGL) n'existe pas en rendu hors écran : il apparaît vide dans ces captures.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
if "IMAGEVERS3D_DATA" not in os.environ:  # lancé à la main : dossier de données jetable avec une licence de développement
    sys.path.insert(0, str(REPO / "tools"))
    import dev_license

    dev_license.install(Path(tempfile.mkdtemp(prefix="i3d_data_")))
sys.path.insert(0, str(REPO / "src"))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from imagevers3d import license as lic  # noqa: E402
from imagevers3d import studio  # noqa: E402


class StubLicense:
    """Gestionnaire de licence factice : un état fixe, pour photographier l'écran Licence dans chacun de ses états."""

    def __init__(self, state, message, days_left=None, license_id=None):
        self._status = lic.LicenseStatus(state, message, days_left, license_id)

    def status(self):
        return self._status


class DemoEngine:
    """Moteur factice : l'interface se rend sans PyTorch ni GPU ; la génération échoue exprès pour montrer l'erreur."""

    def triposg_ready(self):
        return False

    def device_label(self):
        return "GPU : NVIDIA GeForce RTX 4070 Ti"

    def preprocess(self, image, remove_bg, ratio, progress):
        progress("Détourage de l'image…")
        time.sleep(0.05)
        return image.convert("RGB")

    def generate(self, prepared, resolution, progress):
        raise RuntimeError("Mémoire GPU insuffisante. Choisis une qualité plus basse (Rapide ou Équilibré) et réessaie.")


def demo_image():
    img = Image.new("RGB", (640, 480), (232, 232, 232))
    ImageDraw.Draw(img).ellipse((170, 100, 470, 400), fill=(196, 92, 52))
    return img.convert("RGBA")


def window(mode, app):
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "reglages.ini"), QSettings.Format.IniFormat)
    settings.setValue("theme", mode)
    win = studio.MainWindow(DemoEngine(), settings)
    win.resize(1280, 800)
    win.show()
    QTest.qWait(250)
    return win


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    win = window("dark", app)
    win.grab().save(str(out / "ecran-vide-sombre.png"))
    win.set_input(demo_image())
    win.on_generate()
    end = time.time() + 10
    while win._task is not None and time.time() < end:
        QTest.qWait(30)
    QTest.qWait(300)
    win.grab().save(str(out / "ecran-erreur-sombre.png"))
    win.close()
    win = window("light", app)
    win.set_input(demo_image())
    win.grab().save(str(out / "ecran-image-chargee-clair.png"))
    win.close()

    # Écran Licence : accueil (sombre), essai terminé (clair, texte 130 %), essai en cours dans l'étude, licence active
    lic._license_keys.SERVER_URL = "https://licence.exemple.fr"
    lic._license_keys.BUY_URL = "https://exemple.fr/acheter"
    shots = (
        ("licence-accueil-sombre.png", "dark", 1.0, StubLicense("none", "")),
        ("licence-essai-termine-clair.png", "light", 1.3, StubLicense("trial_expired", "L'essai gratuit est terminé.", 0)),
        ("ecran-essai-sombre.png", "dark", 1.0, StubLicense("trial", "Essai gratuit : 5 jours restants.", 5, "trial")),
        ("licence-active-sombre.png", "dark", 1.0, StubLicense("licensed", "Licence active.", None, "L123")),
    )
    for name, mode, scale, manager in shots:
        lic.set_manager(manager)
        settings = QSettings(str(Path(tempfile.mkdtemp()) / "reglages.ini"), QSettings.Format.IniFormat)
        settings.setValue("theme", mode)
        settings.setValue("text_scale", scale)
        win = studio.MainWindow(DemoEngine(), settings)
        win.resize(1280, 800)
        win.show()
        if name.startswith("licence-active"):
            win.on_open_license()
        QTest.qWait(300)
        win.grab().save(str(out / name))
        win.close()
    lic.set_manager(None)
    print("captures écrites dans", out)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/images"))
