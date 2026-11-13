"""Accès au protocole partagé avec le logiciel (source unique : src/imagevers3d/_licproto.py).

Dans l'image Docker, `_licproto.py` et `_ed25519.py` sont copiés à côté de ce fichier ; en développement on utilise
directement les sources du logiciel (le dépôt contient les deux dossiers)."""

try:
    from . import _licproto as proto
except ImportError:  # développement : sources du logiciel
    from imagevers3d import _licproto as proto

LicenseError = proto.LicenseError

__all__ = ["proto", "LicenseError"]
