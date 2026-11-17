"""
mesh_tools.py - Nettoyage, allègement et colorisation des maillages (sans PyTorch, sans GPU).

Utilisé par le moteur TripoSG : sa forme sort en gris, avec près d'un million de faces, parfois
accompagnée de petits morceaux flottants. Ces fonctions :
  - retirent les morceaux flottants minuscules ;
  - allègent le maillage (décimation quadrique) en gardant les arêtes vives ;
  - colorient la surface en projetant l'image d'origine par l'avant, puis en propageant les
    couleurs le long de la surface pour les zones cachées (dos, dessous).

Convention : le maillage est dans le repère de l'export (Y vers le haut, face avant vers +Z), et
l'image est vue de face : un sommet (x, y, z) correspond au pixel (x, y) de l'image.
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy import ndimage, sparse
from scipy.sparse.csgraph import connected_components


def vertex_adjacency(faces: np.ndarray, n_vertices: int) -> sparse.csr_matrix:
    """Matrice d'adjacence (symétrique, 0/1) entre sommets reliés par une arête."""
    f = np.asarray(faces)
    rows = np.concatenate([f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]])
    cols = np.concatenate([f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]])
    adjacency = sparse.coo_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n_vertices, n_vertices)).tocsr()
    adjacency.data[:] = 1.0
    return adjacency


def remove_small_components(mesh: trimesh.Trimesh, min_fraction: float = 0.02) -> tuple[trimesh.Trimesh, int]:
    """Retire les morceaux détachés dont le nombre de faces est inférieur à `min_fraction` du plus gros.

    Renvoie (maillage, nombre de morceaux retirés). Les vraies pièces séparées (une épée qui ne touche
    pas la main, par exemple) sont bien plus grosses que ce seuil et sont conservées.
    """
    faces = np.asarray(mesh.faces)
    count, labels = connected_components(vertex_adjacency(faces, len(mesh.vertices)), directed=False)
    if count <= 1:
        return mesh, 0
    face_counts = np.bincount(labels[faces[:, 0]], minlength=count)
    keep = face_counts >= face_counts.max() * min_fraction
    if keep.all():
        return mesh, 0
    cleaned = trimesh.Trimesh(np.asarray(mesh.vertices), faces[keep[labels[faces[:, 0]]]], process=False)
    cleaned.remove_unreferenced_vertices()
    return cleaned, int((~keep).sum())


def simplify(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Décimation quadrique vers `target_faces` faces ; renvoie le maillage tel quel s'il est déjà plus léger
    ou si la bibliothèque `fast_simplification` est absente."""
    if target_faces <= 0 or len(mesh.faces) <= target_faces:
        return mesh
    try:
        import fast_simplification
    except ImportError:
        return mesh
    reduction = 1.0 - target_faces / float(len(mesh.faces))
    vertices, faces = fast_simplification.simplify(
        np.ascontiguousarray(mesh.vertices, dtype=np.float32), np.ascontiguousarray(mesh.faces, dtype=np.int32),
        target_reduction=reduction, agg=3,
    )
    return trimesh.Trimesh(vertices, faces, process=False)


def _alpha_box(alpha: np.ndarray) -> tuple[int, int, int, int]:
    rows, cols = np.where(alpha)
    return int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())


class _FrontCamera:
    """Caméra de face : projection en perspective faible, ajustée pour que la silhouette du maillage
    recouvre celle de l'objet dans l'image.

    Paramètres ajustés : k (force de la perspective : les parties proches de la caméra paraissent plus
    grandes), échelle, décalage x/y. Le calage de départ aligne les boîtes englobantes.
    """

    def __init__(self, vertices: np.ndarray, alpha_box: tuple[int, int, int, int]) -> None:
        self.v = vertices
        self.x0, self.x1, self.y0, self.y1 = alpha_box
        self.zc = float(vertices[:, 2].min() + vertices[:, 2].max()) / 2.0
        self.closing = 2  # itérations de fermeture morphologique : plus si les sommets sont clairsemés

    def project(self, params):
        """Coordonnées (px, py) en pixels de l'image pour tous les sommets."""
        k, scale_mul, tx, ty = params
        v = self.v
        w = 1.0 / np.maximum(1.0 - k * (v[:, 2] - self.zc), 0.2)
        X, Y = v[:, 0] * w, v[:, 1] * w
        xl, xh, yl, yh = X.min(), X.max(), Y.min(), Y.max()
        s = 0.5 * ((self.x1 - self.x0 + 1) / max(xh - xl, 1e-9) + (self.y1 - self.y0 + 1) / max(yh - yl, 1e-9)) * scale_mul
        px = (self.x0 + self.x1) / 2.0 + (X - (xl + xh) / 2.0) * s + tx
        py = (self.y0 + self.y1) / 2.0 - (Y - (yl + yh) / 2.0) * s + ty
        return px, py


def _silhouette_iou(camera: _FrontCamera, params, alpha: np.ndarray) -> float:
    height, width = alpha.shape
    px, py = camera.project(params)
    mask = np.zeros((height, width), dtype=bool)
    mask[np.clip(np.rint(py).astype(int), 0, height - 1), np.clip(np.rint(px).astype(int), 0, width - 1)] = True
    mask = ndimage.binary_closing(mask, iterations=camera.closing)
    union = (mask | alpha).sum()
    return float((mask & alpha).sum() / union) if union else 0.0


def fit_front_camera(vertices: np.ndarray, alpha: np.ndarray, work_size: int = 512):
    """Cale le maillage sur la silhouette de l'image. Renvoie (caméra à pleine résolution, paramètres, IoU)."""
    from scipy.optimize import minimize

    height, width = alpha.shape
    factor = min(1.0, work_size / float(max(height, width)))
    small = alpha if factor == 1.0 else ndimage.zoom(alpha.astype(np.float32), factor, order=1) > 0.5
    camera_small = _FrontCamera(vertices, _alpha_box(small))
    spacing = (max(int(small.sum()), 1) / float(len(vertices))) ** 0.5  # écart moyen entre sommets, en pixels
    camera_small.closing = int(np.clip(np.ceil(1.5 * spacing), 2, 6))
    start = np.array([0.15, 1.0, 0.0, 0.0])
    result = minimize(
        lambda p: -_silhouette_iou(camera_small, p, small), start, method="Nelder-Mead",
        options=dict(initial_simplex=np.array([start, start + [0.12, 0, 0, 0], start + [0, 0.03, 0, 0],
                                                start + [0, 0, 6, 0], start + [0, 0, 0, 6]]),
                     xatol=1e-3, fatol=1e-4, maxiter=160),
    )
    params = result.x.copy()
    params[0] = float(np.clip(params[0], 0.0, 0.6))
    iou = _silhouette_iou(camera_small, params, small)
    camera = _FrontCamera(vertices, _alpha_box(alpha))
    full = params.copy()
    full[2:] = params[2:] / factor  # les décalages sont en pixels : on revient à la pleine résolution
    return camera, full, iou


def project_colors_front(
    vertices: np.ndarray,
    faces: np.ndarray,
    rgba: np.ndarray,
    min_facing: float = 0.5,
    min_iou: float = 0.55,
) -> tuple[np.ndarray, float, float]:
    """Couleurs par sommet (uint8, N x 4) à partir d'une image vue de face.

    Alignement : une caméra de face (perspective faible) est ajustée pour que la silhouette du maillage
    recouvre celle de l'objet dans l'image. Les sommets visibles de face prennent la couleur du pixel ;
    les autres reçoivent la couleur de leurs voisins, de proche en proche le long de la surface (pas à
    travers l'espace : pas de fuite entre deux pièces proches), en privilégiant les voisins de même
    orientation.

    Renvoie (couleurs, part des sommets lus directement dans l'image, qualité du calage entre 0 et 1).
    Lève ValueError si l'image et le maillage ne se correspondent pas (calage < min_iou).
    """
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces)
    n_vertices = len(v)
    height, width = rgba.shape[:2]
    alpha = rgba[:, :, 3] > 127
    if not alpha.any():
        raise ValueError("L'image ne contient aucun pixel d'objet.")

    camera, params, iou = fit_front_camera(v, alpha)
    if iou < min_iou:
        raise ValueError(f"L'image et le maillage ne se correspondent pas assez (calage {iou:.2f}).")
    px, py = camera.project(params)
    lo, hi = v.min(axis=0), v.max(axis=0)

    # --- normales de sommets
    face_normals = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    normals = np.zeros_like(v)
    for k in range(3):
        np.add.at(normals, f[:, k], face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)

    # --- visibilité de face : tampon de profondeur dans le repère de l'image (le même que celui de la
    # lecture des couleurs : une pièce cachée derrière l'épée doit l'être aussi dans ce repère)
    edge_vectors = v[f[:, 1]] - v[f[:, 0]]
    median_edge = float(np.median(np.linalg.norm(edge_vectors, axis=1))) or 1e-3
    pixels_per_unit = (py.max() - py.min()) / max(hi[1] - lo[1], 1e-9)
    cell = max(1.0, 1.5 * median_edge * pixels_per_unit)
    ix = np.clip(((px - px.min()) / cell).astype(int), 0, None)
    iy = np.clip(((py - py.min()) / cell).astype(int), 0, None)
    zbuffer = np.full((iy.max() + 1, ix.max() + 1), -np.inf)
    np.maximum.at(zbuffer, (iy, ix), v[:, 2])
    tolerance = 4.0 * median_edge
    visible = (v[:, 2] >= zbuffer[iy, ix] - tolerance) & (normals[:, 2] > min_facing)

    # --- lecture des couleurs (le bord de l'objet est érodé : il garde souvent un liseré du fond)
    erosion = max(2, int(round(0.002 * max(height, width))))
    inside = ndimage.binary_erosion(alpha, iterations=erosion)
    sample_alpha = ndimage.map_coordinates(inside.astype(np.float32), [py, px], order=1, mode="nearest")
    reliable = visible & (sample_alpha > 0.99)
    colors = np.zeros((n_vertices, 3), dtype=np.float32)
    rgb = rgba[:, :, :3].astype(np.float32)
    idx = np.where(reliable)[0]
    for channel in range(3):
        colors[idx, channel] = ndimage.map_coordinates(rgb[:, :, channel], [py[idx], px[idx]], order=1, mode="nearest")

    # --- propagation le long de la surface vers les sommets sans couleur
    known = reliable.copy()
    if not known.any():
        raise ValueError("Aucun sommet n'est visible de face : l'image et le maillage ne correspondent pas.")
    adjacency = vertex_adjacency(f, n_vertices).tocoo()
    similarity = np.clip((normals[adjacency.row] * normals[adjacency.col]).sum(axis=1), 0.0, 1.0) ** 4 + 1e-3
    weights = sparse.csr_matrix((similarity.astype(np.float32), (adjacency.row, adjacency.col)), shape=(n_vertices, n_vertices))
    for _ in range(3000):
        unknown = np.where(~known)[0]
        if len(unknown) == 0:
            break
        rows = weights[unknown]
        counts = rows @ known.astype(np.float32)
        gain = counts > 0
        if not gain.any():  # morceau isolé sans voisin colorié : couleur moyenne
            colors[unknown] = colors[known].mean(axis=0)
            known[unknown] = True
            break
        sums = rows @ (colors * known[:, None])
        targets = unknown[gain]
        colors[targets] = sums[gain] / counts[gain][:, None]
        known[targets] = True

    out = np.empty((n_vertices, 4), dtype=np.uint8)
    out[:, :3] = np.clip(np.rint(colors), 0, 255)
    out[:, 3] = 255
    return out, float(reliable.mean()), iou


def transfer_vertex_colors(source: trimesh.Trimesh, target_vertices: np.ndarray) -> np.ndarray:
    """Couleur de chaque sommet cible = celle du sommet le plus proche du maillage source (uint8, N x 4)."""
    from scipy.spatial import cKDTree

    _, nearest = cKDTree(np.asarray(source.vertices)).query(np.asarray(target_vertices), k=1)
    return np.asarray(source.visual.vertex_colors)[nearest]


def to_gltf_colors(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Copie du maillage avec des couleurs de sommets linéaires, comme l'exige glTF (COLOR_0).

    Les couleurs de l'image sont en sRGB : écrites telles quelles dans un .glb, elles paraîtraient
    délavées dans Blender et les visionneuses. Sans couleurs, le maillage est renvoyé tel quel.
    """
    if getattr(mesh.visual, "kind", None) != "vertex":
        return mesh
    srgb = np.asarray(mesh.visual.vertex_colors, dtype=np.float32)[:, :3] / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    colors = np.empty((len(srgb), 4), dtype=np.uint8)
    colors[:, :3] = np.rint(linear * 255.0)
    colors[:, 3] = 255
    out = mesh.copy()
    out.visual = trimesh.visual.ColorVisuals(out, vertex_colors=colors)
    return out


def prepare_for_export(mesh: trimesh.Trimesh, glb: bool) -> trimesh.Trimesh:
    """Copie prête à exporter : métadonnées effacées (elles contiennent des chemins de ton ordinateur),
    normales lisses calculées (sinon les logiciels 3D affichent un rendu facetté) et, pour un .glb, couleurs
    linéaires. Un maillage gris reçoit une couleur uniforme claire plutôt qu'un matériau absent."""
    out = to_gltf_colors(mesh) if glb else mesh
    if out is mesh:  # pas de copie faite en amont : on ne touche jamais au maillage de l'appelant
        out = mesh.copy()
    out.metadata = {}
    if getattr(out.visual, "kind", None) != "vertex":
        gray = np.empty((len(out.vertices), 4), dtype=np.uint8)
        gray[:] = (170, 176, 190, 255) if not glb else (101, 107, 121, 255)
        out.visual = trimesh.visual.ColorVisuals(out, vertex_colors=gray)
    _ = out.vertex_normals  # calculées avant l'export : trimesh ne les écrit que si elles existent
    return out
