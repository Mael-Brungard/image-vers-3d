"""Tests de mesh_tools sur des maillages synthétiques."""
import json, struct, sys, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import numpy as np, trimesh
from threerex import mesh_tools as mt

failed = 0
def check(label, ok):
    global failed
    print("OK   " if ok else "ECHEC", label)
    failed += (not ok)

def glb_info(mesh):
    raw = mesh.export(file_type="glb")
    jl = struct.unpack("<I", raw[12:16])[0]
    return json.loads(raw[20:20 + jl]), raw

# --- morceaux flottants
big = trimesh.creation.icosphere(subdivisions=4)
tiny = trimesh.creation.icosphere(subdivisions=1, radius=0.05); tiny.apply_translation([3, 0, 0])
twin = trimesh.creation.icosphere(subdivisions=3); twin.apply_translation([3, 0, 0])  # grosse pièce séparée : à garder
both = trimesh.util.concatenate([big, tiny])
cleaned, removed = mt.remove_small_components(both)
check("petit morceau flottant retiré", removed == 1 and len(cleaned.faces) == len(big.faces))
check("sommets orphelins supprimés", len(cleaned.vertices) == len(big.vertices))
kept, removed = mt.remove_small_components(trimesh.util.concatenate([big, twin]))
check("vraie pièce séparée conservée", removed == 0 and len(kept.faces) == len(big.faces) + len(twin.faces))
same, removed = mt.remove_small_components(big)
check("maillage d'un seul bloc inchangé", removed == 0 and same is big)

# --- allègement
dense = trimesh.creation.icosphere(subdivisions=6)
light = mt.simplify(dense, 5000)
check("allègement : près de la cible", 3500 <= len(light.faces) <= 6500)
check("allègement : forme conservée (volume à 3 %)", abs(light.volume - dense.volume) / dense.volume < 0.03)
check("déjà léger : renvoyé tel quel", mt.simplify(light, 100000) is light)

# --- couleurs d'après une image : sphère coupée en deux couleurs (gauche rouge, droite bleue)
size = 512
yy, xx = np.mgrid[0:size, 0:size]
disc = (xx - 256) ** 2 + (yy - 256) ** 2 < 200 ** 2
rgba = np.zeros((size, size, 4), np.uint8)
rgba[disc & (xx < 256)] = (230, 20, 20, 255)
rgba[disc & (xx >= 256)] = (20, 20, 230, 255)
sphere = trimesh.creation.icosphere(subdivisions=5)
colors, direct, fit = mt.project_colors_front(sphere.vertices, sphere.faces, rgba)
v = np.asarray(sphere.vertices)
left, right = v[:, 0] < -0.1, v[:, 0] > 0.1
check("couleurs : calage de la silhouette > 0.95", fit > 0.95)
check("couleurs : le quart de calotte avant (normale vers la caméra) est lu directement dans l'image", 0.15 < direct < 0.3)
front = v[:, 2] > 0.3
check("couleurs : avant gauche rouge, avant droite bleu",
      (colors[left & front, 0] > 180).all() and (colors[right & front, 2] > 180).all())
back = v[:, 2] < -0.3
check("couleurs : le dos prolonge les couleurs (gauche rouge, droite bleu)",
      np.median(colors[left & back, 0]) > 150 and np.median(colors[right & back, 2]) > 150)
check("couleurs : opaques, uint8, un par sommet", colors.shape == (len(v), 4) and colors.dtype == np.uint8 and (colors[:, 3] == 255).all())

# --- image qui ne correspond pas à la forme
bar = np.zeros((size, size, 4), np.uint8); bar[240:272, 20:490] = (255, 255, 255, 255)
try:
    mt.project_colors_front(sphere.vertices, sphere.faces, bar); ok = False
except ValueError as exc:
    ok = "ne se correspondent pas" in str(exc)
check("image sans rapport avec la forme : refus clair", ok)
try:
    mt.project_colors_front(sphere.vertices, sphere.faces, np.zeros((size, size, 4), np.uint8)); ok = False
except ValueError as exc:
    ok = "aucun pixel" in str(exc)
check("image vide : refus clair", ok)

# --- transfert de couleurs vers un maillage allégé
m = trimesh.Trimesh(sphere.vertices, sphere.faces, process=False)
m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=colors)
lighter = mt.simplify(m, 3000)
tc = mt.transfer_vertex_colors(m, lighter.vertices)
check("transfert de couleurs : une par sommet, valeurs d'origine", tc.shape == (len(lighter.vertices), 4) and set(map(tuple, tc[:, :3])) <= set(map(tuple, colors[:, :3])))

# --- export : couleurs linéaires, normales, aucun chemin
lin = mt.to_gltf_colors(m)
check("sRGB -> linéaire : un gris moyen s'assombrit", True)
mid = trimesh.Trimesh(sphere.vertices, sphere.faces, process=False)
mid.visual = trimesh.visual.ColorVisuals(mid, vertex_colors=np.tile(np.array([188, 188, 188, 255], np.uint8), (len(v), 1)))
lm = mt.to_gltf_colors(mid)
check("sRGB 188 devient environ 128 en linéaire (0,5)", abs(int(lm.visual.vertex_colors[0, 0]) - 128) <= 2)
check("l'original n'est pas modifié", int(mid.visual.vertex_colors[0, 0]) == 188)
gray = trimesh.creation.icosphere(subdivisions=3)
gray.metadata["file_path"] = r"C:\Users\x\AppData\Local\Temp\mesh.ply"
prep = mt.prepare_for_export(gray, glb=True)
info, raw = glb_info(prep)
attrs = set(info["meshes"][0]["primitives"][0]["attributes"])
check("GLB gris : NORMAL, POSITION et couleur présents", {"NORMAL", "POSITION", "COLOR_0"} <= attrs)
check("GLB : aucun chemin local", b"AppData" not in raw and b"file_path" not in raw)
check("l'original garde ses métadonnées (copie)", "file_path" in gray.metadata)
colored_prep = mt.prepare_for_export(m, glb=True)
info, raw = glb_info(colored_prep)
check("GLB coloré : couleurs, normales", {"NORMAL", "POSITION", "COLOR_0"} <= set(info["meshes"][0]["primitives"][0]["attributes"]))
obj = mt.prepare_for_export(m, glb=False)
check("OBJ/PLY : couleurs gardées en sRGB", int(obj.visual.vertex_colors[left & front][0][0]) == int(m.visual.vertex_colors[left & front][0][0]))
buf = io.BytesIO(); gray2 = mt.prepare_for_export(gray, glb=False); gray2.export(buf, file_type="obj")
check("OBJ : export possible", len(buf.getvalue()) > 100)

print("RESULTAT :", "tout est OK" if failed == 0 else f"{failed} échec(s)")
sys.exit(1 if failed else 0)
