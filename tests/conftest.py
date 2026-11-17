"""Réglages communs : Qt hors écran, dossier de données jetable, code source importable sans installation."""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Les tests ne doivent jamais écrire dans le vrai dossier de données de l'utilisateur.
os.environ.setdefault("THREEREX_DATA", tempfile.mkdtemp(prefix="i3d_test_data_"))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
