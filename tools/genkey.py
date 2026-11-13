"""Génère la paire de clés qui signe les licences (à faire UNE fois, sur ta machine, hors dépôt).

    pip install cryptography
    python tools/genkey.py

Affiche une clé PRIVÉE (pour le serveur : variable I3D_SIGNING_KEY ; à ranger dans un gestionnaire de mots de passe, jamais
dans GitHub) et une clé PUBLIQUE (pour la variable de dépôt GitHub I3D_LICENSE_PUBKEYS, déjà au bon format « k1=… »).
Ne dépend que de `cryptography` : le dépôt n'a pas besoin d'être installé.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "src")]

try:
    from licenseserver import admin
except ModuleNotFoundError as exc:
    raise SystemExit(f"Module manquant : {exc.name}. Installe-le avec :  python -m pip install cryptography") from exc

if __name__ == "__main__":
    raise SystemExit(admin.main(["genkey"]))
