"""Image vers 3D : application de bureau, 100 % locale, qui transforme une image en modèle 3D.

Ce fichier reste volontairement léger (aucun import lourd) : le programme de calcul TripoSG, qui tourne dans
un autre environnement Python, importe ce paquet.
"""

from importlib import metadata

try:
    __version__ = metadata.version("imagevers3d")
except metadata.PackageNotFoundError:  # exécution depuis les sources, sans installation
    __version__ = "0.0.0+dev"

APP_NAME = "Image vers 3D"

from . import paths as _paths  # noqa: E402

_paths.configure_environment()
