"""Vérifie la nouvelle orientation : le « devant » brut de TripoSR (+X, haut = +Z, droite de l'image = +Y)
doit devenir : devant = +Z, haut = +Y, droite = +X à l'export, et devant = vers la caméra (-Y), haut = +Z,
droite = +X dans la visionneuse."""
import sys
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import trimesh
from threerex.geometry import ORIENTATION, Y_UP_TO_Z_UP, display_arrays

ok = True
def check(name, cond):
    global ok
    print("OK   " if cond else "ECHEC", name)
    ok &= bool(cond)

front, up, right = np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, 1.0, 0])
check("rotation propre (det = +1)", np.isclose(np.linalg.det(ORIENTATION), 1.0))
check("export : devant brut +X -> +Z", np.allclose(ORIENTATION @ front, [0, 0, 1]))
check("export : haut brut +Z -> +Y", np.allclose(ORIENTATION @ up, [0, 1, 0]))
check("export : droite brute +Y -> +X", np.allclose(ORIENTATION @ right, [1, 0, 0]))

view = Y_UP_TO_Z_UP @ ORIENTATION
check("visionneuse : devant -> -Y (vers la caméra à azimut -90)", np.allclose(view @ front, [0, -1, 0]))
check("visionneuse : haut -> +Z", np.allclose(view @ up, [0, 0, 1]))
check("visionneuse : droite de l'image -> +X (pas de miroir)", np.allclose(view @ right, [1, 0, 0]))

# Forme asymétrique : un « nez » en +X brut (le devant), un « chapeau » en haut, une « main » à droite
mesh = trimesh.creation.icosphere(subdivisions=2)
v = np.asarray(mesh.vertices).copy()
v[:, 0] = np.where(v[:, 0] > 0.7, v[:, 0] * 2.0, v[:, 0])      # nez en +X
mesh.vertices = v
nose_raw = mesh.vertices[mesh.vertices[:, 0].argmax()]

# chemin export non texturé (même code que image_to_3d.export_mesh)
exp = mesh.copy()
t = np.eye(4); t[:3, :3] = ORIENTATION
exp.apply_transform(t)
check("export : le nez pointe vers +Z", exp.vertices[:, 2].argmax() == mesh.vertices[:, 0].argmax())
# chemin avec texture (sommets @ ORIENTATION.T) identique
alt = np.asarray(mesh.vertices) @ ORIENTATION.T
check("chemins avec/sans texture identiques", np.allclose(alt, exp.vertices))
check("sens des faces conservé (volume > 0)", exp.volume > 0)

verts, faces, colors, zmin = display_arrays(mesh)
nose = verts[mesh.vertices[:, 0].argmax()]
check("visionneuse : le nez est du côté caméra (y minimal)", verts[:, 1].argmin() == mesh.vertices[:, 0].argmax() and nose[1] < 0)
print("RESULTAT :", "OK" if ok else "ECHEC")
sys.exit(0 if ok else 1)
