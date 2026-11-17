"""Réglages communs : Qt hors écran, dossier de données jetable, code source importable sans installation."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Les tests ne doivent jamais écrire dans le vrai dossier de données de l'utilisateur.
os.environ.setdefault("THREEREX_DATA", tempfile.mkdtemp(prefix="i3d_test_data_"))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _ignore_system_motion_setting(monkeypatch):
    """Les tests ne dépendent pas du réglage « Afficher les animations dans Windows » de la machine : les serveurs de CI le
    coupent, et l'application passerait alors en mouvement réduit (comportement voulu, mais qui fausserait les tests)."""
    try:
        from threerex import theme
    except ImportError:  # PySide6 absent : aucune interface à neutraliser
        return
    monkeypatch.setattr(theme, "system_prefers_reduced_motion", lambda: False)
