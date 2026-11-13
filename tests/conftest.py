"""Réglages communs : Qt hors écran, dossier de données jetable, code source importable sans installation."""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Les tests ne doivent jamais écrire dans le vrai dossier de données de l'utilisateur (ni toucher à sa vraie licence) :
# le dossier est toujours un dossier jetable, même si IMAGEVERS3D_DATA est défini dans l'environnement.
DATA_DIR = tempfile.mkdtemp(prefix="i3d_test_data_")
os.environ["IMAGEVERS3D_DATA"] = DATA_DIR
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

# Licence de développement : sans elle, l'application et les fonctions de calcul affichent l'écran Licence. Les tests du
# système de licence lui-même installent leur propre gestionnaire (voir tests/test_licensing_*.py).
import dev_license  # noqa: E402

dev_license.install(DATA_DIR)
