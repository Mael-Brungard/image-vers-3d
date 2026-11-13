"""
mcubes_fallback.py - Remplaçant de `torchmcubes`, sans aucune compilation.

TripoSR extrait son maillage avec `torchmcubes.marching_cubes`, une extension C++/CUDA
qu'il faut compiler (Visual Studio, CUDA Toolkit...), ce qui échoue souvent sous Windows.
Ce module fournit la même fonction avec scikit-image (calcul sur le processeur) :
quelques secondes au plus par modèle, pour un maillage équivalent.

Équivalence vérifiée contre un port fidèle du code C++ de torchmcubes, dans les conditions
exactes d'utilisation de TripoSR : même aire, mêmes bornes, même sens des faces, surfaces
confondues à moins d'un millième de voxel près.

Utilisation : `install_if_needed()` avant d'importer TripoSR. Si le vrai `torchmcubes` est
installé, il reste prioritaire.
"""

from __future__ import annotations

import importlib
import sys
import types

import numpy as np

# Convention de torchmcubes, reprise telle quelle :
#   - le volume est indexé [axe0][axe1][axe2] ;
#   - les sommets renvoyés sont (axe2, axe1, axe0) en coordonnées d'indices
#     (TripoSR les remet ensuite dans l'ordre avec v[..., [2, 1, 0]]) ;
#   - la surface est celle où volume == seuil, objet = valeurs supérieures au seuil.
# `gradient_direction="ascent"` donne le même sens de faces (normales vers l'extérieur).
GRADIENT_DIRECTION = "ascent"


def marching_cubes_numpy(volume: np.ndarray, level: float) -> tuple[np.ndarray, np.ndarray]:
    """Version numpy : renvoie (sommets float32 (V, 3), faces int32 (F, 3))."""
    from skimage import measure

    vol = np.ascontiguousarray(volume, dtype=np.float32)
    try:
        verts, faces, _normals, _values = measure.marching_cubes(
            vol, level=level, gradient_direction=GRADIENT_DIRECTION, allow_degenerate=False
        )
    except (ValueError, RuntimeError):
        # Seuil hors de la plage du volume, ou aucune surface : maillage vide (comme torchmcubes).
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32)
    verts = np.ascontiguousarray(verts[:, ::-1], dtype=np.float32)
    return verts, np.ascontiguousarray(faces, dtype=np.int32)


def marching_cubes(vol, thresh: float):
    """Même signature que torchmcubes.marching_cubes : renvoie deux tenseurs PyTorch."""
    import torch

    verts, faces = marching_cubes_numpy(vol.detach().cpu().numpy(), float(thresh))
    return torch.from_numpy(verts).to(vol.device), torch.from_numpy(faces).to(vol.device)


def install_if_needed() -> bool:
    """Enregistre ce remplaçant sous le nom `torchmcubes` si le vrai est absent ou inutilisable.

    Renvoie True si le remplaçant est utilisé, False si le vrai torchmcubes est disponible.
    """
    try:
        importlib.import_module("torchmcubes")
        return False
    except Exception:  # noqa: BLE001 - ImportError, ou erreur de chargement de l'extension compilée
        module = types.ModuleType("torchmcubes")
        module.marching_cubes = marching_cubes
        module.__version__ = "fallback-scikit-image"
        module.HAS_CUDA = False
        sys.modules["torchmcubes"] = module
        return True
