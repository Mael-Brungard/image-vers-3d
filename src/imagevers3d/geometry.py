"""
geometry.py - Orientation des maillages et conversion pour l'affichage.

Ce module n'importe ni PyTorch ni TripoSR : il peut donc être chargé par
l'interface avant le moteur, et testé seul.
"""

from __future__ import annotations

import numpy as np
import trimesh

# Orientation de l'export. Le maillage brut de TripoSR a l'axe Z vers le haut et regarde vers +X
# (c'est la position de la caméra de l'image d'entrée : azimut 0, voir tsr/utils.py).
# On applique -90° autour de X (Z devient le haut, axe Y), puis -90° autour de Y : l'objet est
# "debout" avec Y vers le haut ET il regarde vers +Z, comme le veut la convention glTF.
# Les visionneuses .glb, Blender (import glTF) et la plupart des logiciels 3D l'affichent donc
# de face. (La démo officielle de TripoSR utilise +90° autour de Y : l'objet regarde alors vers -Z,
# ce qui n'est correct que dans la visionneuse de Gradio.)
ORIENTATION: np.ndarray = (
    trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0])
    @ trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
)[:3, :3]

# La visionneuse intégrée (pyqtgraph) a l'axe Z vers le haut, alors que le
# modèle exporté a l'axe Y vers le haut : (x, y, z) -> (x, -z, y).
Y_UP_TO_Z_UP: np.ndarray = np.array(
    [[1.0, 0.0, 0.0],
     [0.0, 0.0, -1.0],
     [0.0, 1.0, 0.0]]
)


IDENTITY: np.ndarray = np.eye(3)


def rotation(axis: str, degrees: float) -> np.ndarray:
    """Matrice de rotation 3x3 autour de l'axe « x », « y » ou « z » (repère de l'export, Y vers le haut)."""
    vector = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[axis]
    return trimesh.transformations.rotation_matrix(np.radians(degrees), vector)[:3, :3]


def display_arrays(mesh: trimesh.Trimesh, target_size: float = 1.6, orientation: np.ndarray = ORIENTATION):
    """Prépare un maillage pour la visionneuse.

    `orientation` est la rotation qui amène le maillage dans le repère de l'export (Y vers le haut,
    face vers +Z) : ORIENTATION pour la sortie brute de TripoSR, une matrice identité (éventuellement
    corrigée à la main) pour TripoSG, dont la sortie est déjà dans ce repère.

    Renvoie (sommets, faces, couleurs, z_min) :
      - sommets : float32 (N, 3), orientés comme l'export, centrés, taille normalisée
      - faces   : int32 (M, 3)
      - couleurs: float32 (N, 4) entre 0 et 1, ou None si le maillage n'a pas de couleurs
      - z_min   : altitude du bas de l'objet (pour poser la grille dessous)
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    vertices = vertices @ np.asarray(orientation).T @ Y_UP_TO_Z_UP.T

    low, high = vertices.min(axis=0), vertices.max(axis=0)
    extent = float((high - low).max()) or 1.0
    vertices = (vertices - (low + high) / 2.0) * (target_size / extent)

    colors = None
    visual = getattr(mesh, "visual", None)
    if visual is not None and getattr(visual, "kind", None) == "vertex":
        raw = np.asarray(visual.vertex_colors, dtype=np.float32)
        if raw.shape == (len(vertices), 4):
            colors = raw / 255.0

    faces = np.asarray(mesh.faces, dtype=np.int32)
    return vertices.astype(np.float32), faces, colors, float(vertices[:, 2].min())
