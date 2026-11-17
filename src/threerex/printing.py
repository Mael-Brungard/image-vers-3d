"""
printing.py - Prépare un maillage pour l'impression 3D : réparation, échelle en millimètres, pose à plat, fichier STL.

Aucune dépendance à PyTorch ni à l'interface : ce sont des fonctions pures, testables seules.

Entrée : un maillage dans le repère de l'export (Y vers le haut), à n'importe quelle échelle.
Sortie : un maillage Z vers le haut, en millimètres, posé sur Z = 0 et centré en X et Y, avec un rapport franc de ce
qui a été fait. Les étapes, dans l'ordre :

  1. les sommets confondus sont soudés (un .glb en contient en double le long des coutures de texture) ;
  2. les faces dégénérées ou en double et les petits morceaux flottants sont retirés ;
  3. le sens des faces est rendu cohérent ;
  4. chaque trou est fermé par un éventail de triangles (un fond plat reste plat, un petit trou se rebouche) ;
  5. si le dessous n'est pas plat, il est coupé de quelques millimètres pour que la figurine tienne sur le plateau ;
  6. le modèle est mis à l'échelle à la hauteur demandée.

Ce que la réparation ne garantit PAS : une épaisseur de paroi suffisante, l'absence d'auto-intersections, des
supports. « Étanche » veut dire : chaque arête est partagée par exactement deux faces (une surface fermée).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from scipy.sparse.csgraph import connected_components

from .geometry import ORIENTATION, Y_UP_TO_Z_UP
from .mesh_tools import vertex_adjacency

log = logging.getLogger(__name__)

DEFAULT_HEIGHT_MM = 150
HEIGHT_RANGE_MM = (10, 400)
FLATTEN_FRACTION = 0.015  # on coupe au plus 1,5 % de la hauteur pour aplatir le dessous
FRAGMENT_FACES = 0.005  # un morceau détaché est retiré s'il a moins de 0,5 % des faces du plus gros...
FRAGMENT_EXTENT = 0.10  # ... ET s'il mesure moins de 10 % de la diagonale du modèle (une vraie petite pièce reste)


@dataclass
class PrintOptions:
    height_mm: int = DEFAULT_HEIGHT_MM
    flatten: bool = True


@dataclass
class PrintReport:
    watertight: bool
    open_edges: int
    non_manifold_edges: int
    shells: int
    holes_closed: int
    holes_left: int
    fragments_removed: int
    flattened_mm: float
    size_mm: tuple[float, float, float]  # largeur (X), profondeur (Y), hauteur (Z)
    volume_cm3: float | None  # seulement si la surface est fermée
    faces: int

    def summary(self) -> str:
        """Une ligne pour la barre d'état."""
        w, d, h = self.size_mm
        parts = ["surface fermée" if self.watertight else "NON étanche", f"{w:.0f} × {d:.0f} × {h:.0f} mm"]
        if self.volume_cm3 is not None:
            parts.append(f"environ {self.volume_cm3:.0f} cm³")
        return " · ".join(parts)

    def lines(self) -> list[str]:
        """Le détail, en français, pour le message affiché après l'enregistrement."""
        w, d, h = self.size_mm
        out = []
        if self.watertight:
            out.append("Surface fermée (étanche) : le fichier est prêt pour le logiciel de tranchage.")
        else:
            problems = []
            if self.open_edges:
                problems.append(f"{self.open_edges} arêtes ouvertes")
            if self.non_manifold_edges:
                problems.append(f"{self.non_manifold_edges} arêtes partagées par plus de deux faces")
            out.append("Surface NON étanche (" + ", ".join(problems) + ") : ouvre le fichier dans PrusaSlicer, "
                       "Meshmixer ou Blender pour finir la réparation avant d'imprimer.")
        out.append(f"Taille : {w:.0f} × {d:.0f} mm au sol, {h:.0f} mm de haut.")
        if self.volume_cm3 is not None:
            out.append(f"Volume : environ {self.volume_cm3:.0f} cm³ de matière (plein).")
        if self.holes_closed:
            out.append(f"{self.holes_closed} {_plural(self.holes_closed, 'trou fermé', 'trous fermés')}.")
        if self.fragments_removed:
            out.append(f"{self.fragments_removed} {_plural(self.fragments_removed, 'petit morceau flottant retiré', 'petits morceaux flottants retirés')}.")
        if self.flattened_mm > 0:
            out.append(f"Dessous aplati sur {str(round(self.flattened_mm, 1)).replace('.', ',')} mm pour tenir à plat.")
        if self.shells > 1:
            out.append(f"{self.shells} pièces séparées : elles ne tiennent ensemble que si elles se touchent. "
                       "Vérifie-le dans le logiciel de tranchage.")
        return out


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


# --------------------------------------------------------------------------------------------------------------------
#  Étapes de réparation (tableaux numpy : sommets float64 (N, 3), faces int64 (M, 3))
# --------------------------------------------------------------------------------------------------------------------
def _weld(vertices: np.ndarray, faces: np.ndarray, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Soude les sommets situés au même endroit (à `tolerance` près)."""
    keys = np.round(vertices / tolerance).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)  # numpy 2.0 : la forme de `inverse` varie avec `axis`
    return vertices[first], inverse[faces]


def _clean_faces(faces: np.ndarray) -> np.ndarray:
    """Retire les faces dont deux sommets sont confondus et les faces en double."""
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 2] != faces[:, 0])
    faces = faces[keep]
    if len(faces) == 0:
        return faces
    _, first = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    return faces[np.sort(first)]


def _compact(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Retire les sommets que plus aucune face n'utilise."""
    used, inverse = np.unique(faces, return_inverse=True)
    return vertices[used], np.asarray(inverse).reshape(faces.shape)


def _drop_fragments(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, int]:
    """Retire les petits morceaux détachés (poussières, éclats) ; une vraie pièce séparée est conservée."""
    count, labels = connected_components(vertex_adjacency(faces, len(vertices)), directed=False)
    if count <= 1:
        return faces, 0
    face_label = labels[faces[:, 0]]
    sizes = np.bincount(face_label, minlength=count)
    present = np.flatnonzero(sizes)
    if len(present) <= 1:
        return faces, 0
    whole = float(np.linalg.norm(vertices[np.unique(faces)].max(axis=0) - vertices[np.unique(faces)].min(axis=0)))
    drop = np.zeros(count, dtype=bool)
    for label in present:
        if sizes[label] >= sizes.max() * FRAGMENT_FACES:
            continue
        points = vertices[np.unique(faces[face_label == label])]
        if float(np.linalg.norm(points.max(axis=0) - points.min(axis=0))) < whole * FRAGMENT_EXTENT:
            drop[label] = True
    if not drop.any():
        return faces, 0
    return faces[~drop[face_label]], int(drop.sum())


def _edge_stats(faces: np.ndarray, n_vertices: int) -> tuple[int, int]:
    """(arêtes ouvertes, arêtes partagées par plus de deux faces)."""
    if len(faces) == 0:
        return 0, 0
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    _, counts = np.unique(key[:, 0].astype(np.int64) * n_vertices + key[:, 1], return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum())


def _boundary_edges(faces: np.ndarray, n_vertices: int) -> np.ndarray:
    """Arêtes de bord, orientées comme dans la face qui les porte."""
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    code = key[:, 0].astype(np.int64) * n_vertices + key[:, 1]
    _, inverse, counts = np.unique(code, return_inverse=True, return_counts=True)
    return edges[counts[np.asarray(inverse).reshape(-1)] == 1]


def _trace_loops(edges: np.ndarray) -> tuple[list[list[int]], int]:
    """Boucles formées par les arêtes de bord (a -> b, dans le sens des faces).

    Renvoie (boucles de sommets distincts, nombre de chaînes restées ouvertes). Un sommet où deux trous se touchent
    est géré : le parcours en sort des boucles simples, jamais une boucle qui repasse deux fois au même endroit.
    """
    out: dict[int, list[int]] = {}
    for a, b in edges.tolist():
        out.setdefault(a, []).append(b)
    loops: list[list[int]] = []
    open_chains = 0
    for start in list(out):
        while out[start]:
            trail, where, cur = [start], {start: 0}, start
            while True:
                options = out.get(cur)
                if not options:
                    if len(trail) > 1:
                        open_chains += 1
                    break
                nxt = options.pop()
                if nxt in where:  # on referme une boucle : on la détache et on continue depuis son point de départ
                    i = where[nxt]
                    loops.append(trail[i:])
                    for v in trail[i + 1:]:
                        del where[v]
                    del trail[i + 1:]
                else:
                    where[nxt] = len(trail)
                    trail.append(nxt)
                cur = nxt
    return loops, open_chains


def _fill_holes(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Ferme chaque trou par un éventail de triangles autour du centre du trou.

    Un fond plat et convexe redevient parfaitement plat ; un petit trou se rebouche ; un grand trou irrégulier devient
    une calotte fermée, pas toujours jolie mais imprimable. Renvoie (sommets, faces, trous fermés, trous non fermés).
    """
    edges = _boundary_edges(faces, len(vertices))
    if len(edges) == 0:
        return vertices, faces, 0, 0
    loops, open_chains = _trace_loops(edges)
    new_vertices: list[np.ndarray] = []
    new_faces: list[tuple[int, int, int]] = []
    next_index = len(vertices)
    closed = 0
    left = open_chains
    for loop in loops:
        n = len(loop)
        if n < 3:
            left += 1
            continue
        if n == 3:
            a, b, c = loop
            new_faces.append((b, a, c))
        else:
            centre = vertices[loop].mean(axis=0)
            new_vertices.append(centre)
            for i in range(n):
                new_faces.append((loop[(i + 1) % n], loop[i], next_index))
            next_index += 1
        closed += 1
    if new_vertices:
        vertices = np.vstack([vertices, np.asarray(new_vertices)])
    if new_faces:
        faces = np.vstack([faces, np.asarray(new_faces, dtype=np.int64)])
    return vertices, faces, closed, left


def _fix_winding(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Rend le sens des faces cohérent d'un voisin à l'autre (sans effet si c'est déjà le cas)."""
    mesh = trimesh.Trimesh(vertices, faces.copy(), process=False)
    try:
        if not mesh.is_winding_consistent:
            trimesh.repair.fix_winding(mesh)
            return np.asarray(mesh.faces, dtype=np.int64)
    except Exception:  # noqa: BLE001 - réparation facultative : on garde le maillage tel quel
        log.warning("Sens des faces non corrigé", exc_info=True)
    return faces


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    tri = vertices[faces]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def _fix_orientation(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Si le plus gros morceau est « retourné » (volume négatif : normales vers l'intérieur), retourne toutes les faces."""
    if len(faces) == 0:
        return faces
    count, labels = connected_components(vertex_adjacency(faces, len(vertices)), directed=False)
    tri = vertices[faces]
    volume = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0
    per_shell = np.bincount(labels[faces[:, 0]], weights=volume, minlength=count)
    if per_shell[np.argmax(np.abs(per_shell))] < 0:
        return faces[:, ::-1].copy()
    return faces


def _needs_flat_base(vertices: np.ndarray, faces: np.ndarray) -> bool:
    """Vrai si le dessous n'est pas déjà plat : moins de 2 % de l'emprise est faite de faces horizontales posées au point bas."""
    low = vertices.min(axis=0)
    extent = vertices.max(axis=0) - low
    tri = vertices[faces]
    on_floor = (tri[:, :, 2] <= low[2] + 0.002 * extent[2]).all(axis=1)
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1)
    facing_down = normal[:, 2] < -0.9 * length
    flat_area = float(0.5 * length[on_floor & facing_down].sum())
    return flat_area < 0.02 * float(extent[0] * extent[1])


def _repair(vertices: np.ndarray, faces: np.ndarray, tolerance: float) -> tuple[np.ndarray, np.ndarray, int, int, int]:
    """Soudure, nettoyage, sens des faces, fermeture des trous. Renvoie (sommets, faces, morceaux retirés, trous fermés, trous restants)."""
    vertices, faces = _weld(vertices, faces, tolerance)
    faces = _clean_faces(faces)
    if len(faces) == 0:
        raise ValueError("Le modèle ne contient aucune surface utilisable.")
    faces, removed = _drop_fragments(vertices, faces)
    vertices, faces = _compact(vertices, faces)
    faces = _fix_winding(vertices, faces)
    vertices, faces, closed, left = _fill_holes(vertices, faces)
    faces = _fix_orientation(vertices, faces)
    return vertices, faces, removed, closed, left


# --------------------------------------------------------------------------------------------------------------------
#  API
# --------------------------------------------------------------------------------------------------------------------
def make_printable(mesh: trimesh.Trimesh, height_mm: float = DEFAULT_HEIGHT_MM,
                   flatten_base: bool = True) -> tuple[trimesh.Trimesh, PrintReport]:
    """Maillage prêt à imprimer (Z vers le haut, millimètres, posé sur Z = 0) et rapport. `mesh` : repère de l'export (Y en haut)."""
    if not height_mm or height_mm <= 0:
        raise ValueError("La hauteur doit être positive.")
    vertices = np.asarray(mesh.vertices, dtype=np.float64) @ Y_UP_TO_Z_UP.T
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(faces) == 0 or not np.isfinite(vertices).all():
        raise ValueError("Le modèle ne contient aucune surface utilisable.")
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    if diagonal <= 0:
        raise ValueError("Le modèle est vide.")
    tolerance = diagonal * 1e-6

    vertices, faces, removed, closed, left = _repair(vertices, faces, tolerance)

    flattened = 0.0
    if flatten_base and _needs_flat_base(vertices, faces):
        low = float(vertices[:, 2].min())
        height = float(vertices[:, 2].max()) - low
        plane = low + FLATTEN_FRACTION * height
        try:
            cut = trimesh.intersections.slice_faces_plane(vertices, faces, [0.0, 0.0, 1.0], [0.0, 0.0, plane])
            if len(cut[1]):
                # le disque qui ferme la coupe n'est pas un « trou réparé » : on ne le compte pas, mais un échec, si
                vertices, faces, more_removed, _cap, more_left = _repair(
                    np.asarray(cut[0], dtype=np.float64), np.asarray(cut[1], dtype=np.int64), tolerance)
                removed += more_removed
                left += more_left
                flattened = plane - low
        except Exception:  # noqa: BLE001 - le dessous reste tel quel ; le rapport ne prétend rien
            log.warning("Dessous non aplati", exc_info=True)

    low, high = vertices.min(axis=0), vertices.max(axis=0)
    extent = high - low
    if float(extent[2]) <= 0:
        raise ValueError("Le modèle est plat : impossible de le mettre à l'échelle.")
    scale = float(height_mm) / float(extent[2])
    vertices = (vertices - np.array([(low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0, low[2]])) * scale

    open_edges, non_manifold = _edge_stats(faces, len(vertices))
    watertight = open_edges == 0 and non_manifold == 0
    count, labels = connected_components(vertex_adjacency(faces, len(vertices)), directed=False)
    shells = int(len(np.unique(labels[faces[:, 0]])))
    volume = _signed_volume(vertices, faces) / 1000.0 if watertight else None  # mm³ -> cm³
    result = trimesh.Trimesh(vertices, faces, process=False)
    report = PrintReport(
        watertight=watertight, open_edges=open_edges, non_manifold_edges=non_manifold, shells=shells,
        holes_closed=closed, holes_left=left, fragments_removed=removed, flattened_mm=flattened * scale,
        size_mm=(float(extent[0] * scale), float(extent[1] * scale), float(height_mm)),
        volume_cm3=volume if volume is not None and volume > 0 else None, faces=len(faces),
    )
    return result, report


def export_stl(mesh: trimesh.Trimesh, path: Path, height_mm: float = DEFAULT_HEIGHT_MM,
               flatten_base: bool = True) -> PrintReport:
    """Répare `mesh` (repère de l'export) et l'écrit en STL binaire dans `path`. Renvoie le rapport."""
    printable, report = make_printable(mesh, height_mm, flatten_base)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(trimesh.exchange.stl.export_stl(printable))
    return report


def source_mesh(result: dict) -> trimesh.Trimesh:
    """Maillage d'un résultat de l'interface, dans le repère de l'export (Y en haut) et avec les corrections faites à la main."""
    engine = result["engine"]
    extra = np.asarray(result.get("extra", np.eye(3)), dtype=np.float64)
    if engine == "trellis":
        mesh = trimesh.load(io.BytesIO(result["glb"]), file_type="glb", force="mesh", process=False)
        rotation = extra
    elif engine == "triposg":
        mesh = result["mesh_export"]
        rotation = extra
    else:  # TripoSR : sortie brute, redressée comme à l'export
        mesh = result["mesh"]
        rotation = ORIENTATION
    vertices = np.asarray(mesh.vertices, dtype=np.float64) @ np.asarray(rotation).T
    return trimesh.Trimesh(vertices, np.asarray(mesh.faces, dtype=np.int64), process=False)


def size_ratios(mesh: trimesh.Trimesh, rotation: np.ndarray | None = None) -> tuple[float, float]:
    """(largeur / hauteur, profondeur / hauteur) du maillage debout : sert à annoncer la taille au sol avant l'export.

    `rotation` : celle qui amène `mesh` dans le repère de l'export (Y en haut), comme pour l'affichage.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    if rotation is not None:
        vertices = vertices @ np.asarray(rotation).T
    extent = np.ptp(vertices, axis=0)  # repère de l'export : X, Y = hauteur, Z
    height = float(extent[1]) or 1.0
    return float(extent[0]) / height, float(extent[2]) / height
